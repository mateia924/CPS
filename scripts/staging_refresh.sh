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
# Sprint 6.6.3b (item b, docs/ops/RLS.md): `pg_dump --no-privileges`
# (scripts/backup.sh) strips every GRANT and RLS policy from the dump,
# so every restore onto staging must re-run `manage.py setup_rls`
# (apps.tenants.services.configure_database_roles_and_rls, idempotent)
# and then verify pg_policies' row count actually matches the
# tenant-scoped-table count — a silent policy gap would mean staging's
# UAT session runs with RLS quietly OFF on some table instead of
# exercising the same isolation production will have.
#
# Sprint 6.6.3d: `--code-only` ships a CODE change (a bug fix found
# mid-UAT, say) to staging WITHOUT ever touching its database — no
# drop/recreate, no restore, no anonymize. A real UAT session's own
# in-progress data (tenants created, forms half-filled, whatever state
# the human tester built up) must survive this exactly like a live
# `deploy.sh` run leaves port 3000's own data untouched — the only
# thing this mode changes is which code is running. Still re-runs
# `manage.py setup_rls` (idempotent either way, and cheap insurance if
# a migration in this same code change touched a tenant-scoped table)
# and still runs a real smoke test before declaring success.
#
# Usage: scripts/staging_refresh.sh               (full restore, as always)
#        scripts/staging_refresh.sh --code-only    (code only, data untouched)
#        make staging-refresh

CODE_ONLY=0
if [ "${1:-}" = "--code-only" ]; then
  CODE_ONLY=1
fi

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="/opt/cps-backups"
COMPOSE="docker compose -p cps-staging --env-file $REPO_DIR/.env.staging -f docker-compose.yml -f docker-compose.staging.yml"

log() { echo "[staging_refresh $(date -Iseconds)] $1"; }

if [ ! -f "$REPO_DIR/.env.staging" ]; then
  echo "ERROR: $REPO_DIR/.env.staging not found — copy .env.staging.example and fill it in first." >&2
  exit 1
fi

# Sprint 6.6.4: every backup.sh-produced file is encrypted with the
# passphrase in .env (never .env.staging — that passphrase belongs to
# the dev/live backup the staging refresh RESTORES FROM, not to
# staging's own, separate environment) — sourced first, deliberately,
# so .env.staging's own POSTGRES_* etc. below still win if the two
# files ever share a variable name.
set -a
source "$REPO_DIR/.env"
source "$REPO_DIR/.env.staging"
set +a

if [ "$CODE_ONLY" = "0" ]; then
  LATEST_BACKUP="$(find "$BACKUP_DIR" -maxdepth 1 -name 'cps-db-*.sql.gz.gpg' -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)"
  if [ -z "$LATEST_BACKUP" ]; then
    echo "ERROR: no cps-db-*.sql.gz.gpg backup found in $BACKUP_DIR — run scripts/backup.sh first." >&2
    exit 1
  fi
  log "using backup: $LATEST_BACKUP"
  if [ -z "${CPS_BACKUP_ENCRYPTION_PASSPHRASE:-}" ]; then
    echo "ERROR: CPS_BACKUP_ENCRYPTION_PASSPHRASE is not set in .env — cannot decrypt $LATEST_BACKUP." >&2
    exit 1
  fi
else
  log "--code-only: staging's database is left exactly as it is — no drop, no restore, no anonymize."
fi

cd "$REPO_DIR/infra"

if [ "$CODE_ONLY" = "0" ]; then
  log "step 1/7: bringing up staging's own independent stack (project cps-staging)"
  $COMPOSE up -d --build

  log "step 2/7: stopping backend/celery_worker to release their DB connections"
  $COMPOSE stop backend celery_worker

  log "step 3/7: dropping and recreating the staging database"
  $COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -c \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$POSTGRES_DB' AND pid <> pg_backend_pid();"
  $COMPOSE exec -T postgres dropdb -U "$POSTGRES_USER" --if-exists "$POSTGRES_DB"
  $COMPOSE exec -T postgres createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" "$POSTGRES_DB"

  log "step 4/7: decrypting and restoring the dev backup into it"
  gpg --batch --yes --passphrase "$CPS_BACKUP_ENCRYPTION_PASSPHRASE" --decrypt "$LATEST_BACKUP" 2>/dev/null \
    | gunzip -c | $COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 > /dev/null

  log "step 5/7: bringing backend/celery_worker back up and applying any pending migration"
  $COMPOSE up -d backend celery_worker
  $COMPOSE exec -T backend python manage.py migrate --noinput
else
  log "step 1/6: building images from the current code (not starting backend/celery_worker yet — see next step)"
  $COMPOSE build backend celery_worker frontend

  # §0 rule 1 (docs/prompts/sprint-6.6.md): a backup before any
  # migration, full stop — the guard in apps.tenants.management.
  # commands.migrate enforces this universally (it checks "is there a
  # recent docs/ops/backups.log line", not which specific database
  # that backup covers), so even a code-only staging run needs one.
  # This backs up the LIVE/infra database (backup.sh's own, fixed
  # target) — never staging's, which --code-only leaves untouched by
  # design — but that's exactly what the guard itself checks for, and
  # a fresh live backup is never wasted effort anyway.
  log "step 2/6: scripts/backup.sh (satisfies the migrate guard below; backs up live, not staging — staging's own data is untouched either way)"
  "$REPO_DIR/scripts/backup.sh" "staging_refresh.sh --code-only"

  # Deliberately a one-off throwaway container (`run --rm`), not
  # `exec` on the persistent "backend" service and not relying on
  # that service's own entrypoint chain (migrate && collectstatic &&
  # ... && gunicorn) to do it implicitly — starting the PERSISTENT
  # container first and only satisfying the guard afterward races its
  # own startup migrate attempt and crash-loops it (found live:
  # "Container ... is restarting, wait until running"). This runs to
  # completion fully independently, with the guard already satisfied,
  # before the persistent service ever starts.
  log "step 3/6: applying any pending migration (one-off container, independent of backend's own startup)"
  $COMPOSE run --rm --entrypoint '' backend python manage.py migrate --noinput

  log "step 4/6: restarting backend/celery_worker/frontend/nginx from the freshly built images"
  $COMPOSE up -d backend celery_worker frontend nginx
fi

# Sprint 6.6.0 (found while validating this exact script): nginx
# resolves its "backend" upstream once and keeps that connection/IP —
# recreating backend above (a new container, a new IP) left nginx
# still holding the OLD IP, so every request 502'd until nginx itself
# restarted. Restarting nginx here forces a fresh DNS lookup.
log "restarting nginx so it re-resolves backend's new address"
$COMPOSE restart nginx

log "re-applying RLS roles/grants/policies, then verifying the policy count"
$COMPOSE exec -T backend python manage.py setup_rls
RLS_CHECK="$($COMPOSE exec -T backend python manage.py shell -c "
from django.db import connection
from apps.common.rls import tenant_scoped_tables
tables = [name for name, _model in tenant_scoped_tables()]
with connection.cursor() as cursor:
    cursor.execute(
        \"SELECT count(*) FROM pg_policies WHERE schemaname = 'public' \"
        \"AND policyname = 'tenant_isolation' AND tablename = ANY(%s)\",
        [tables],
    )
    policy_count = cursor.fetchone()[0]
print(f'{len(tables)} {policy_count}')
" | tail -1 | tr -d '\r')"
TABLE_COUNT="$(echo "$RLS_CHECK" | cut -d' ' -f1)"
POLICY_COUNT="$(echo "$RLS_CHECK" | cut -d' ' -f2)"
if [ "$TABLE_COUNT" != "$POLICY_COUNT" ]; then
  echo "ERROR: $TABLE_COUNT tenant-scoped table(s) but only $POLICY_COUNT tenant_isolation polic(y/ies) — RLS is not fully applied. Aborting before serving staging." >&2
  exit 1
fi
log "RLS verified: $POLICY_COUNT/$TABLE_COUNT tenant-scoped tables have the tenant_isolation policy."

if [ "$CODE_ONLY" = "1" ]; then
  log "step 5/6: waiting for the backend to actually accept connections"
  READY=0
  for _ in $(seq 1 30); do
    STATUS="$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:${STAGING_HTTP_PORT:-3001}/admin/login/" || true)"
    if [ "$STATUS" != "502" ] && [ "$STATUS" != "503" ] && [ "$STATUS" != "000" ]; then
      READY=1
      break
    fi
    sleep 1
  done
  [ "$READY" = "1" ] || { echo "ERROR: backend never accepted a connection within 30s (last status: ${STATUS:-none})" >&2; exit 1; }

  log "step 6/6: smoke test (staging's own real data — no anonymize ran, so this uses whatever the current UAT session's own Fatma Accountant credentials already are)"
  cd "$REPO_DIR"
  if ! SMOKE_BASE_URL="http://localhost:${STAGING_HTTP_PORT:-3001}/api" \
     SMOKE_SUBDOMAIN="${CODE_ONLY_SMOKE_SUBDOMAIN:-fatma}" \
     SMOKE_EMAIL="${CODE_ONLY_SMOKE_EMAIL:-accountant@fatma.staging.test}" \
     SMOKE_PASSWORD="${CODE_ONLY_SMOKE_PASSWORD:-$STAGING_UAT_PASSWORD}" \
     ./scripts/smoke.sh; then
    echo "ERROR: smoke test failed against staging after the code-only deploy — investigate before trusting this session." >&2
    exit 1
  fi
  log "done — staging is now running the current code, UAT session data untouched."
  exit 0
fi

log "step 7/7: anonymizing every user's email domain and rewriting their password, re-arming 2FA, and invalidating sessions"
$COMPOSE exec -T backend python manage.py anonymize_staging_users --password "$STAGING_UAT_PASSWORD"

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
