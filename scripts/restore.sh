#!/usr/bin/env bash
set -euo pipefail

# Restore a CPS backup into a database — sprint 5.0 (docs/CFO_REVIEW_1.md
# O1: "اختبار استعادة فعلي موثّق مرة قبل أول عميل وشهريًا بعده"). Defaults
# to a NEW, separate database so a routine restore test never touches the
# live one — pass the real $POSTGRES_DB explicitly only for an actual
# disaster-recovery restore, and only after deliberately dropping/
# replacing the current database outside this script (never automatic).
#
# For the AUTOMATED monthly health-check (own log, own pass/fail
# verdict, finds the latest backup itself), see scripts/restore_test.sh
# instead — this script stays the manual, ad hoc "restore THIS exact
# file for me to look at" tool the two were never meant to duplicate.
#
# Sprint 6.6.4: every backup.sh-produced file is encrypted now
# (cps-db-*.sql.gz.gpg) — a .gpg file is decrypted with
# CPS_BACKUP_ENCRYPTION_PASSPHRASE (.env) before anything else touches
# it; a plain .sql.gz (any backup from before this sprint) still works
# exactly as before, unchanged.
#
# Block A (2026-10-20): --from is required. The dump must carry, in
# docs/ops/backups.log, the db= identity of the environment named — read
# now from that environment's running Postgres (scripts/restore_lib.sh).
# Until today this script checked nothing: a staging dump could be restored
# onto live with nothing in the way. Restoring into live's own database
# (target-db = $POSTGRES_DB) additionally requires --from live.
# --attachments restores the dump's paired manifest into the MinIO running
# in --attachments-into's container, after the manifest's minio= identity
# and pairs= are checked the same way.
#
# Usage: scripts/restore.sh --from live|staging|dev <backup-file.sql.gz[.gpg]> [target-db-name]
#            [--attachments <manifest.gpg> --attachments-into <minio-container>]
#   target-db-name defaults to "${POSTGRES_DB}_restore_test".
usage() {
  echo "Usage: $0 --from live|staging|dev <backup-file.sql.gz[.gpg]> [target-db-name] [--attachments <manifest.gpg> --attachments-into <minio-container>]" >&2
  exit 1
}
FROM="" MANIFEST="" ATT_CONTAINER=""
POSITIONAL=()
while [ $# -gt 0 ]; do
  case "$1" in
    --from) FROM="${2:-}"; shift 2 ;;
    --attachments) MANIFEST="${2:-}"; shift 2 ;;
    --attachments-into) ATT_CONTAINER="${2:-}"; shift 2 ;;
    -*) usage ;;
    *) POSITIONAL+=("$1"); shift ;;
  esac
done
[ -n "$FROM" ] && [ "${#POSITIONAL[@]}" -ge 1 ] || usage
[ -z "$MANIFEST" ] || [ -n "$ATT_CONTAINER" ] || { echo "--attachments needs --attachments-into <minio-container>" >&2; exit 1; }
BACKUP_FILE="${POSITIONAL[0]}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ ! -f "$BACKUP_FILE" ]; then
  echo "Backup file not found: $BACKUP_FILE" >&2
  exit 1
fi
set -a
source "$REPO_DIR/.env"
set +a
# shellcheck source=restore_lib.sh
source "$REPO_DIR/scripts/restore_lib.sh"
TARGET_DB="${POSITIONAL[1]:-${POSTGRES_DB}_restore_test}"
COMPOSE="docker compose --env-file $REPO_DIR/.env"

# Nothing is created, dropped or written before both checks pass.
cps_require_dump_from "$BACKUP_FILE" "$FROM"
if [ "$TARGET_DB" = "$POSTGRES_DB" ] && [ "$FROM" != "live" ]; then
  echo "REFUSED: restoring into live's own database ($POSTGRES_DB) needs a dump from live, not from $FROM." >&2
  exit 1
fi
if [ -n "$MANIFEST" ]; then
  [ -f "$MANIFEST" ] || { echo "Manifest not found: $MANIFEST" >&2; exit 1; }
  cps_require_manifest_from "$MANIFEST" "$FROM" "$BACKUP_FILE"
fi
cd "$REPO_DIR/infra"

echo "[$(date -Iseconds)] Dropping (if exists) and creating $TARGET_DB"
$COMPOSE exec -T postgres dropdb -U "$POSTGRES_USER" --if-exists "$TARGET_DB"
$COMPOSE exec -T postgres createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" "$TARGET_DB"

echo "[$(date -Iseconds)] Restoring $BACKUP_FILE into $TARGET_DB"
if [[ "$BACKUP_FILE" == *.gpg ]]; then
  [ -n "${CPS_BACKUP_ENCRYPTION_PASSPHRASE:-}" ] || { echo "CPS_BACKUP_ENCRYPTION_PASSPHRASE is not set in .env" >&2; exit 1; }
  # Rule 50 (Pre-deploy 4): the passphrase reaches gpg through a file
  # descriptor, never argv — `ps` shows every process's arguments to every
  # user on the host. Safe ONLY because `printf` is a bash BUILTIN: the
  # <(...) subshell writes the value into the pipe without exec'ing a
  # program, so no process ever carries it as an argument. Replace it with
  # /bin/echo, /usr/bin/printf, cat <<< or any external command and the
  # value is back in `ps`, silently. `--passphrase-file` reads the FIRST
  # LINE, the whole of it (spaces included) — the same bytes `--passphrase`
  # used for any single-line .env value, so backups made either way open
  # either way (tests/test_backup_gpg_passphrase.py proves both directions).
  gpg --batch --yes --passphrase-file <(printf '%s' "$CPS_BACKUP_ENCRYPTION_PASSPHRASE") --decrypt "$BACKUP_FILE" 2>/dev/null \
    | gunzip -c | $COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d "$TARGET_DB" -q
else
  gunzip -c "$BACKUP_FILE" | $COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d "$TARGET_DB" -q
fi

echo "[$(date -Iseconds)] Verifying: counting restored tables"
TABLE_COUNT=$($COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d "$TARGET_DB" -t -c \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" | tr -d '[:space:]')
echo "Tables restored: $TABLE_COUNT"

if [ -n "$MANIFEST" ]; then
  STORE="$(dirname "$(dirname "$MANIFEST")")"
  echo "[$(date -Iseconds)] Restoring attachments from $(basename "$MANIFEST") into $ATT_CONTAINER ($MINIO_BUCKET)"
  docker exec -e B="$MINIO_BUCKET" "$ATT_CONTAINER" sh -c "$CPS_MC_ENV; mc mb --ignore-existing \"m/\$B\" >/dev/null"
  cps_restore_attachments "$MANIFEST" "$STORE" "$ATT_CONTAINER" "$MINIO_BUCKET"
fi

echo "[$(date -Iseconds)] Done. This is a separate database — drop it when finished:"
echo "  $COMPOSE exec -T postgres dropdb -U \"$POSTGRES_USER\" \"$TARGET_DB\""
