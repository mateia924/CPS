#!/usr/bin/env bash
set -euo pipefail

# Sprint 6.6.0: the ONLY way staging's data ever changes — restores the
# latest dev backup (the same file scripts/backup.sh already produces
# for the local/live stack) into staging's OWN, fully independent
# Postgres instance (compose project "cps-staging", never "infra"),
# then anonymizes every tenant user (apps.accounts.management.commands.
# anonymize_staging_users — hard-refuses outside CPS_ENVIRONMENT=
# staging): the email's local part is kept but its domain becomes
# "<tenant subdomain>.staging.test" (a real address, e.g. Fatma's own
# Owner login, never actually reaches anyone once it's on staging —
# EMAIL_BACKEND is forced to console there regardless of any EMAIL_HOST
# in .env.staging, config/settings.py), and every password becomes the
# one known STAGING_UAT_PASSWORD value. The login path itself needed no
# code change — it already just matches whatever email is stored.
# Never hand-edit data on staging directly — re-run this instead.
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

log "step 6/6: anonymizing every user's email domain and rewriting their password"
$COMPOSE exec -T backend python manage.py anonymize_staging_users --password "$STAGING_UAT_PASSWORD"
# Sprint 6.6.2 (not built yet): once tenant 2FA / must_change_password /
# session invalidation exist, this step should also re-arm 2FA setup,
# clear must_change_password, and revoke every outstanding refresh
# token for every user on every refresh — a stale staging session
# should never survive past a restore. Add those calls here then.

TENANT_COUNT="$($COMPOSE exec -T backend python manage.py shell -c \
  "from apps.tenants.models import Tenant; print(Tenant.objects.count())" | tail -1 | tr -d '\r')"
log "staging now has $TENANT_COUNT tenant(s) — compare against dev's own count to confirm the restore."

FATMA_OWNER_EMAIL="$($COMPOSE exec -T backend python manage.py shell -c \
  "from apps.accounts.models import User; u = User.objects.filter(tenant__subdomain='fatma', role='owner').first(); print(u.email if u else '')" \
  | tail -1 | tr -d '\r')"

log "done. Email pattern: <local part>@<tenant subdomain>.staging.test — password: the one value below."
if [ -n "$FATMA_OWNER_EMAIL" ]; then
  log "Fatma's Owner login on http://<this-host>:${STAGING_HTTP_PORT:-3001} -> $FATMA_OWNER_EMAIL"
fi
# Sprint 6.6.0 (owner decision): printed once, here, at the very end —
# never logged anywhere persistent (docs/ops/*.log never see it).
log "staging password for every user: $STAGING_UAT_PASSWORD"
