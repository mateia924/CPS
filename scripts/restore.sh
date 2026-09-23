#!/usr/bin/env bash
set -euo pipefail

# Restore a CPS backup into a database — sprint 5.0 (docs/CFO_REVIEW_1.md
# O1: "اختبار استعادة فعلي موثّق مرة قبل أول عميل وشهريًا بعده"). Defaults
# to a NEW, separate database so a routine restore test never touches the
# live one — pass the real $POSTGRES_DB explicitly only for an actual
# disaster-recovery restore, and only after deliberately dropping/
# replacing the current database outside this script (never automatic).
#
# Usage: scripts/restore.sh <backup-file.sql.gz> [target-db-name]
#   target-db-name defaults to "${POSTGRES_DB}_restore_test".

if [ $# -lt 1 ]; then
  echo "Usage: $0 <backup-file.sql.gz> [target-db-name]" >&2
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
gunzip -c "$BACKUP_FILE" | $COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d "$TARGET_DB" -q

echo "[$(date -Iseconds)] Verifying: counting restored tables"
TABLE_COUNT=$($COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d "$TARGET_DB" -t -c \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" | tr -d '[:space:]')
echo "Tables restored: $TABLE_COUNT"

echo "[$(date -Iseconds)] Done. This is a separate database — drop it when finished:"
echo "  $COMPOSE exec -T postgres dropdb -U \"$POSTGRES_USER\" \"$TARGET_DB\""
