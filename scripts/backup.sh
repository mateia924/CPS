#!/usr/bin/env bash
set -euo pipefail

# CPS daily backup — sprint 5.0 (docs/CFO_REVIEW_1.md §5, O1: "لا نسخ
# احتياطي موثّق لـ Postgres إطلاقًا"). Runs from the host (root cron —
# see README "النسخ الاحتياطي"), not inside any container: pg_dump
# talks to the already-running `postgres` service via `docker compose
# exec`, exactly like every other docker command in this project
# (always with --env-file, from infra/ — see the project's own
# recurring gotcha about that).
#
# Usage:      scripts/backup.sh
# Root cron:  0 3 * * * /opt/cps/scripts/backup.sh >> /var/log/cps-backup.log 2>&1

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="/opt/cps-backups"
RETENTION_DAYS=14
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
DUMP_FILE="$BACKUP_DIR/cps-db-$TIMESTAMP.sql.gz"

# Outside every container, root-only — these are the only real copies
# of tenant data (docs/SYSTEM_ANALYSIS.md rule 10: never delete a
# database/volume without explicit permission; a backup is the
# insurance policy against ever needing to test that rule under duress).
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

set -a
source "$REPO_DIR/.env"
set +a
COMPOSE="docker compose --env-file $REPO_DIR/.env"
cd "$REPO_DIR/infra"

echo "[$(date -Iseconds)] Starting backup -> $DUMP_FILE"
$COMPOSE exec -T postgres pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$DUMP_FILE"

if [ ! -s "$DUMP_FILE" ]; then
  echo "[$(date -Iseconds)] ERROR: backup file is empty — deleting and failing loudly." >&2
  rm -f "$DUMP_FILE"
  exit 1
fi
echo "[$(date -Iseconds)] Backup OK: $(du -h "$DUMP_FILE" | cut -f1)"

# Sprint 5.1 adds the MinIO attachments bucket here (mc mirror into
# $BACKUP_DIR/attachments/) once the Attachment model/storage exists —
# not yet, so there is nothing to sync today.

# Cloud destination (CFO_REVIEW_1 O1: "القرص الآن فورًا؛ السحابة قبل
# أول عميل" — an administrative decision, not a code change). Setting
# CPS_BACKUP_CLOUD_BUCKET is a documented no-op today; this deliberately
# does not silently skip a real upload — it says so loudly instead.
if [ -n "${CPS_BACKUP_CLOUD_BUCKET:-}" ]; then
  echo "[$(date -Iseconds)] WARNING: CPS_BACKUP_CLOUD_BUCKET is set but OCI Object Storage upload is not implemented yet (sprint 5.0 debt, see README)." >&2
fi

echo "[$(date -Iseconds)] Pruning backups older than $RETENTION_DAYS days"
find "$BACKUP_DIR" -maxdepth 1 -name 'cps-db-*.sql.gz' -mtime +"$RETENTION_DAYS" -print -delete

echo "[$(date -Iseconds)] Done."
