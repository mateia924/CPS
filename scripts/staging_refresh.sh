#!/usr/bin/env bash
set -euo pipefail

# Sprint 6.6.0: the ONLY way staging's data ever changes — restores the
# latest dev backup (the same file scripts/backup.sh already produces
# for the local/live stack) into staging's OWN, fully independent
# Postgres instance (compose project "cps-staging", never "infra"),
# then rewrites every tenant user's password to one known UAT value
# (real emails stay untouched — see apps/accounts/management/commands/
# reset_passwords_for_staging.py for why this is safe: it hard-refuses
# outside CPS_ENVIRONMENT=staging). Never hand-edit data on staging
# directly — re-run this instead.
#
# Usage: scripts/staging_refresh.sh
#        make staging-refresh

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="/opt/cps-backups"
COMPOSE="docker compose -p cps-staging --env-file $REPO_DIR/.env.staging -f docker-compose.yml -f docker-compose.staging.yml"

log() { echo "[staging_refresh $(date -Iseconds)] $1"; }

if [ ! -f "$REPO_DIR/.env.staging" ]; then
  echo "ERROR: $REPO_DIR/.env.staging not found — copy .env.staging.example and fill it in first." >&2
  exit 1
fi

set -a
source "$REPO_DIR/.env.staging"
set +a

LATEST_BACKUP="$(find "$BACKUP_DIR" -maxdepth 1 -name 'cps-db-*.sql.gz' -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)"
if [ -z "$LATEST_BACKUP" ]; then
  echo "ERROR: no cps-db-*.sql.gz backup found in $BACKUP_DIR — run scripts/backup.sh first." >&2
  exit 1
fi
log "using backup: $LATEST_BACKUP"

cd "$REPO_DIR/infra"

log "step 1/6: bringing up staging's own independent stack (project cps-staging)"
$COMPOSE up -d --build

log "step 2/6: stopping backend/celery_worker to release their DB connections"
$COMPOSE stop backend celery_worker

log "step 3/6: dropping and recreating the staging database"
$COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$POSTGRES_DB' AND pid <> pg_backend_pid();"
$COMPOSE exec -T postgres dropdb -U "$POSTGRES_USER" --if-exists "$POSTGRES_DB"
$COMPOSE exec -T postgres createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" "$POSTGRES_DB"

log "step 4/6: restoring the dev backup into it"
gunzip -c "$LATEST_BACKUP" | $COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 > /dev/null

log "step 5/6: bringing backend/celery_worker back up and applying any pending migration"
$COMPOSE up -d backend celery_worker
$COMPOSE exec -T backend python manage.py migrate --noinput

# Sprint 6.6.0 (found while validating this exact script): nginx
# resolves its "backend" upstream once and keeps that connection/IP —
# recreating backend above (a new container, a new IP) left nginx
# still holding the OLD IP, so every request 502'd until nginx itself
# restarted. Restarting nginx here forces a fresh DNS lookup.
log "restarting nginx so it re-resolves backend's new address"
$COMPOSE restart nginx

log "step 6/6: rewriting every user's password to the known staging UAT value"
$COMPOSE exec -T backend python manage.py reset_passwords_for_staging --password "$STAGING_UAT_PASSWORD"

TENANT_COUNT="$($COMPOSE exec -T backend python manage.py shell -c \
  "from apps.tenants.models import Tenant; print(Tenant.objects.count())" | tr -d '\r')"
log "staging now has $TENANT_COUNT tenant(s) — compare against dev's own count to confirm the restore."
log "done. Log in on http://<this-host>:${STAGING_HTTP_PORT:-3001} with any real tenant email + the known password in .env.staging (STAGING_UAT_PASSWORD)."
