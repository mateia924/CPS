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
# Usage: scripts/staging_refresh.sh --full        (wipe, restore, anonymize)
#        scripts/staging_refresh.sh --code-only   (code only, data untouched)
#        make staging-refresh                     (= --full)
#
# Pre-deploy 1 (2026-10-17): the mode is a required, explicit flag.
# Before, only "--code-only" was checked and ANY other argument — or
# none — meant full: `--code-onyl` (one typo) wiped staging's UAT data,
# and `--full` worked only because it was not "--code-only". The most
# destructive mode is now the one that has to be asked for by name, and
# every argument is checked before anything else runs, .env included.

usage() {
  echo "Usage: scripts/staging_refresh.sh --full | --code-only" >&2
  echo "  --full        back up staging's data, wipe it, restore the latest live backup, anonymize it" >&2
  echo "  --code-only   ship the current code; staging's database is left exactly as it is" >&2
}

MODE=""
for arg in "$@"; do
  case "$arg" in
    --full|--code-only)
      if [ -n "$MODE" ]; then
        echo "ERROR: give exactly one mode — got both $MODE and $arg." >&2
        usage
        exit 2
      fi
      MODE="$arg"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument \"$arg\"." >&2
      usage
      exit 2
      ;;
  esac
done
if [ -z "$MODE" ]; then
  echo "ERROR: no mode given — staging's data is wiped only on an explicit --full." >&2
  usage
  exit 2
fi
CODE_ONLY=0
[ "$MODE" = "--full" ] || CODE_ONLY=1

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

# Pre-deploy 1 (rule 32, docs/SYSTEM_ANALYSIS.md §4): this rehearsal
# runs production's own gates — not a copy of them: scripts/
# production_gates.sh, the same file scripts/deploy.sh sources. This
# script's own steps are only what is truly staging's: build, and in
# full mode back up staging's data, wipe it, restore live's dump and
# anonymize it — before the first gate. Both modes reach the one cps_run_gates
# call below. (Before: full mode had no smoke and no readiness poll,
# neither mode ran add_missing_system_accounts or check_chart_health,
# and both "satisfied" the migrate guard by backing up LIVE — 2026-10-10
# that gap crash-looped cps-staging-backend-1.)
# shellcheck source=production_gates.sh
source "$REPO_DIR/scripts/production_gates.sh"
GATE_REPO_DIR="$REPO_DIR"
GATE_COMPOSE="$COMPOSE"
GATE_BACKUP_TARGET="staging"
GATE_HTTP_PORT="${STAGING_HTTP_PORT:-3001}"

cd "$REPO_DIR/infra"

log "building images from the current code"
$COMPOSE build

# Pre-deploy 1: smoke logs in with the anonymized credentials in both
# modes — full mode anonymizes before the first gate now, so live's own
# logins (smoke.sh's defaults) no longer exist on staging by the time
# smoke runs.
export SMOKE_SUBDOMAIN="${STAGING_SMOKE_SUBDOMAIN:-fatma}"
export SMOKE_EMAIL="${STAGING_SMOKE_EMAIL:-accountant@fatma.staging.test}"
export SMOKE_PASSWORD="${STAGING_SMOKE_PASSWORD:-$STAGING_UAT_PASSWORD}"

# Pre-deploy 1 (2026-10-17): anonymize is what makes a restored copy
# safe to hold at all, not a finishing touch. It used to run after every
# gate passed, so live's real emails and password hashes sat on staging
# for the whole run — and for good, if a gate failed (backend stopped,
# data real, one `up -d` away from serving it). It also meant gate 1
# (backup) wrote live's real data into a second file, under
# /opt/cps-backups/staging. Now it runs straight after the restore, in a
# one-off container (the persistent backend is stopped here), before
# the first gate — no gate needs live's real logins: smoke uses the
# anonymized ones above, and nothing else reads an email or a password.
# It runs on live's schema BEFORE migrate, which is why the command
# names every column it touches (its docstring).
#
# REAL_DATA_ON_STAGING marks the window from the start of the restore to
# the end of anonymize. If the script leaves that window any way other
# than through a finished anonymize — restore failed half-way, anonymize
# failed, Ctrl-C — the EXIT trap drops the staging database: an empty
# staging is a rerun away from fine; one holding live's real logins is
# not. This mode's first step already backed up staging's own data.
REAL_DATA_ON_STAGING=0
drop_unanonymized_data() {
  local rc=$?
  trap - EXIT INT TERM HUP
  if [ "$REAL_DATA_ON_STAGING" = "1" ]; then
    echo "ERROR: stopped between the restore and the end of anonymize — staging may hold live's real logins. Dropping the staging database." >&2
    if $COMPOSE exec -T postgres dropdb -U "$POSTGRES_USER" --if-exists --force "$POSTGRES_DB" </dev/null; then
      echo "Dropped. Staging has no database now; backend/celery_worker stay stopped. Rerun scripts/staging_refresh.sh --full." >&2
    else
      echo "CRITICAL: could NOT drop $POSTGRES_DB — it may hold live's real, unanonymized users. Do not start backend; drop it by hand: cd $REPO_DIR/infra && $COMPOSE exec -T postgres dropdb -U $POSTGRES_USER --force $POSTGRES_DB" >&2
    fi
    rc=1
  fi
  exit "$rc"
}

if [ "$CODE_ONLY" = "0" ]; then
  GATE_BACKUP_REASON="staging_refresh.sh --full (pre-migrate, restored data)"

  log "bringing up staging's postgres (project cps-staging) — the rest starts at the gates"
  $COMPOSE up -d postgres

  # Staging's own data — a UAT session's tenants and edits — is about to
  # be wiped: dumped first, like any data that is about to go.
  log "backing up staging's own data before wiping it"
  cps_gate_backup "staging_refresh.sh --full (staging data before wipe)"

  log "stopping backend/celery_worker to release their DB connections"
  $COMPOSE stop backend celery_worker

  log "dropping and recreating the staging database"
  $COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -c \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$POSTGRES_DB' AND pid <> pg_backend_pid();"
  $COMPOSE exec -T postgres dropdb -U "$POSTGRES_USER" --if-exists "$POSTGRES_DB"
  $COMPOSE exec -T postgres createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" "$POSTGRES_DB"

  trap drop_unanonymized_data EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  trap 'exit 129' HUP
  REAL_DATA_ON_STAGING=1

  # A LOGICAL restore (pg_dump's SQL into psql), and it must stay one —
  # never turn this into copying live's data directory or volume. The
  # migrate guard tells databases apart by the cluster's
  # system_identifier (pg_control_system(), fixed at initdb, stored in
  # the data directory): a logical restore leaves staging's own
  # identifier in place, a file copy carries live's over with it — and
  # then only a database name stands between the two, the very thing
  # that cannot tell live from dev (both postgres/cps). Nothing would
  # fail; the distinction would just be gone.
  log "decrypting and restoring the live backup into it"
  gpg --batch --yes --passphrase "$CPS_BACKUP_ENCRYPTION_PASSPHRASE" --decrypt "$LATEST_BACKUP" 2>/dev/null \
    | gunzip -c | $COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 > /dev/null

  log "anonymizing every user's email domain and rewriting their password, re-arming 2FA, and invalidating sessions — before any gate"
  $COMPOSE run --rm --entrypoint '' backend python manage.py anonymize_staging_users --password "$STAGING_UAT_PASSWORD"
  REAL_DATA_ON_STAGING=0
else
  GATE_BACKUP_REASON="staging_refresh.sh --code-only"
fi

if ! cps_run_gates; then
  echo "ERROR: staging failed production gate \"$CPS_FAILED_GATE\" — the same gate would stop a live deploy. Investigate before trusting this session." >&2
  exit 1
fi

if [ "$CODE_ONLY" = "1" ]; then
  log "done — staging is now running the current code, UAT session data untouched."
  exit 0
fi

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
