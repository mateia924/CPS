#!/usr/bin/env bash
set -euo pipefail

# Sprint 6.6.4 (block 2): proves a real backup.sh file actually
# restores to a working database, automatically, on a schedule — not
# just "the file exists and gzip -t doesn't complain." Restores the
# latest encrypted backup into a throwaway `cps_restore_test` database
# on the SAME "infra" Postgres instance backup.sh itself dumps from
# (never touches the real "cps" database, never touches cps-dev/
# staging), runs `manage.py check` against it, and logs tenant/posted-
# journal-entry counts side by side with the live database's own.
#
# On the PASS/FAIL verdict specifically: this does NOT require the
# restored counts to exactly equal live's. The backup is necessarily a
# point-in-time snapshot — by the time this runs (same day, or up to a
# month later from cron), real work has usually continued on the live
# database, so live's own counts are almost always higher. Treating
# that normal drift as a failure would make this alert fire on every
# single run regardless of backup health, which trains everyone to
# ignore it — the one outcome a restore-health check must never cause.
# The verdict is instead driven by the actual integrity signals:
# `manage.py check` passes, the restore itself completes without
# error, and the restored tenant count is not suspiciously low next to
# live's (a real sign of a truncated/corrupt backup) — never a bare
# count mismatch alone. Both counts are always logged either way, so a
# human reviewing docs/ops/restore_tests.log can still see the raw
# numbers and judge for themselves.
#
# Usage: scripts/restore_test.sh
# Suggested monthly root cron (see docs/ops/BACKUP.md):
#   0 4 1 * * /opt/cps/scripts/restore_test.sh >> /var/log/cps-restore-test.log 2>&1

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="/opt/cps-backups"
RESTORE_TEST_DB="cps_restore_test"
LOG_PATH="$REPO_DIR/docs/ops/restore_tests.log"
# A restored tenant count below this fraction of live's own is treated
# as a real integrity failure, not ordinary drift since the backup was
# taken — see this file's own header for why a bare mismatch alone
# isn't the bar.
MIN_FRACTION_OF_LIVE="0.5"

log() { echo "[restore_test $(date -Iseconds)] $1"; }

set -a
source "$REPO_DIR/.env"
set +a
COMPOSE="docker compose --env-file $REPO_DIR/.env"
cd "$REPO_DIR/infra"

record_result() {
  # status, backup file, restored tenant count, live tenant count,
  # restored posted-entry count, live posted-entry count, detail
  mkdir -p "$(dirname "$LOG_PATH")"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$(date -Iseconds)" "$1" "$2" "$3" "$4" "$5" "$6" "$7" >> "$LOG_PATH"
}

fail() {
  log "FAILED: $1"
  record_result "FAILED" "${BACKUP_NAME:-none}" "${RESTORED_TENANTS:-}" "${LIVE_TENANTS:-}" \
    "${RESTORED_POSTED:-}" "${LIVE_POSTED:-}" "$1"
  exit 1
}

cleanup() {
  $COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=0 -c \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$RESTORE_TEST_DB' AND pid <> pg_backend_pid();" \
    > /dev/null 2>&1 || true
  $COMPOSE exec -T postgres dropdb -U "$POSTGRES_USER" --if-exists "$RESTORE_TEST_DB" > /dev/null 2>&1 || true
}
trap cleanup EXIT

LATEST_BACKUP="$(find "$BACKUP_DIR" -maxdepth 1 -name 'cps-db-*.sql.gz.gpg' -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)"
[ -n "$LATEST_BACKUP" ] || fail "no cps-db-*.sql.gz.gpg backup found in $BACKUP_DIR"
BACKUP_NAME="$(basename "$LATEST_BACKUP")"
log "using backup: $BACKUP_NAME"

[ -n "${CPS_BACKUP_ENCRYPTION_PASSPHRASE:-}" ] || fail "CPS_BACKUP_ENCRYPTION_PASSPHRASE is not set in .env"

cleanup  # in case a previous run was interrupted before its own cleanup ran

log "creating throwaway database $RESTORE_TEST_DB"
$COMPOSE exec -T postgres createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" "$RESTORE_TEST_DB" \
  || fail "could not create $RESTORE_TEST_DB"

log "decrypting and restoring into it"
if ! gpg --batch --yes --passphrase "$CPS_BACKUP_ENCRYPTION_PASSPHRASE" --decrypt "$LATEST_BACKUP" 2>/dev/null \
  | gunzip -c | $COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d "$RESTORE_TEST_DB" -v ON_ERROR_STOP=1 > /dev/null; then
  fail "decrypt/restore of $BACKUP_NAME into $RESTORE_TEST_DB failed"
fi

TEST_DATABASE_URL="postgres://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${RESTORE_TEST_DB}"

# Sprint 6.6.4 (found while validating this exact script): `docker
# compose run` — unlike `exec` — reconciles the WHOLE dependency tree
# against whatever this bare, no-`-f`-overlay $COMPOSE resolves to,
# which recreated the ALREADY-RUNNING live `postgres`/`minio`
# containers the first time this ran (no data lost — named volumes
# survive a recreate — but a live Postgres restart is never something
# a monthly background check should ever risk). `exec` runs inside the
# container deploy.sh already manages, with no reconciliation step at
# all — exactly like every other live-stack script here (backup.sh,
# smoke.sh) already relies on, and `-e` still overrides DATABASE_URL
# for just this one call.
log "running manage.py check against the restored database"
if ! $COMPOSE exec -T -e DATABASE_URL="$TEST_DATABASE_URL" backend python manage.py check; then
  fail "manage.py check failed against the restored database"
fi

RESTORED_TENANTS="$($COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d "$RESTORE_TEST_DB" -t -A -c \
  "SELECT count(*) FROM tenants_tenant;" | tr -d '[:space:]')"
RESTORED_POSTED="$($COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d "$RESTORE_TEST_DB" -t -A -c \
  "SELECT count(*) FROM accounting_journalentry WHERE status = 'posted';" | tr -d '[:space:]')"
LIVE_TENANTS="$($COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -A -c \
  "SELECT count(*) FROM tenants_tenant;" | tr -d '[:space:]')"
LIVE_POSTED="$($COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -A -c \
  "SELECT count(*) FROM accounting_journalentry WHERE status = 'posted';" | tr -d '[:space:]')"

log "tenants: restored=$RESTORED_TENANTS live=$LIVE_TENANTS | posted entries: restored=$RESTORED_POSTED live=$LIVE_POSTED"

[ "${RESTORED_TENANTS:-0}" -gt 0 ] || fail "restored database has zero tenants — treating as a corrupt/empty restore"

if [ "${LIVE_TENANTS:-0}" -gt 0 ]; then
  BELOW_MIN="$(awk -v r="$RESTORED_TENANTS" -v l="$LIVE_TENANTS" -v m="$MIN_FRACTION_OF_LIVE" 'BEGIN { print (r < l * m) ? 1 : 0 }')"
  if [ "$BELOW_MIN" = "1" ]; then
    fail "restored tenant count ($RESTORED_TENANTS) is suspiciously low next to live's ($LIVE_TENANTS) — possible truncated/corrupt backup"
  fi
fi

log "OK"
record_result "OK" "$BACKUP_NAME" "$RESTORED_TENANTS" "$LIVE_TENANTS" "$RESTORED_POSTED" "$LIVE_POSTED" ""
