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
# Usage: scripts/restore.sh <backup-file.sql.gz[.gpg]> [target-db-name]
#   target-db-name defaults to "${POSTGRES_DB}_restore_test".

if [ $# -lt 1 ]; then
  echo "Usage: $0 <backup-file.sql.gz[.gpg]> [target-db-name]" >&2
  exit 1
fi

BACKUP_FILE="$1"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ ! -f "$BACKUP_FILE" ]; then
  echo "Backup file not found: $BACKUP_FILE" >&2
  exit 1
fi

set -a
source "$REPO_DIR/.env"
set +a
TARGET_DB="${2:-${POSTGRES_DB}_restore_test}"
COMPOSE="docker compose --env-file $REPO_DIR/.env"
cd "$REPO_DIR/infra"

echo "[$(date -Iseconds)] Dropping (if exists) and creating $TARGET_DB"
$COMPOSE exec -T postgres dropdb -U "$POSTGRES_USER" --if-exists "$TARGET_DB"
$COMPOSE exec -T postgres createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" "$TARGET_DB"

echo "[$(date -Iseconds)] Restoring $BACKUP_FILE into $TARGET_DB"
if [[ "$BACKUP_FILE" == *.gpg ]]; then
  [ -n "${CPS_BACKUP_ENCRYPTION_PASSPHRASE:-}" ] || { echo "CPS_BACKUP_ENCRYPTION_PASSPHRASE is not set in .env" >&2; exit 1; }
  gpg --batch --yes --passphrase "$CPS_BACKUP_ENCRYPTION_PASSPHRASE" --decrypt "$BACKUP_FILE" 2>/dev/null \
    | gunzip -c | $COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d "$TARGET_DB" -q
else
  gunzip -c "$BACKUP_FILE" | $COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d "$TARGET_DB" -q
fi

echo "[$(date -Iseconds)] Verifying: counting restored tables"
TABLE_COUNT=$($COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d "$TARGET_DB" -t -c \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" | tr -d '[:space:]')
echo "Tables restored: $TABLE_COUNT"

echo "[$(date -Iseconds)] Done. This is a separate database — drop it when finished:"
echo "  $COMPOSE exec -T postgres dropdb -U \"$POSTGRES_USER\" \"$TARGET_DB\""
