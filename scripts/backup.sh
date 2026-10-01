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
# Usage:      scripts/backup.sh ["reason for this backup"]
# Root cron:  0 3 * * * /opt/cps/scripts/backup.sh >> /var/log/cps-backup.log 2>&1
#
# Sprint 6.5.12 (owner audit finding: no literal record linking a
# backup file to the migration/decision it preceded — only inferred
# from timestamps after the fact): every run appends one line to
# docs/ops/backups.log (date, git hash, backup filename, and this
# optional $1 reason) — the standing §11 rule ("scripts/backup.sh قبل
# أي migration تلمس بيانات") now leaves a real, committed trail instead
# of relying on backup-file timestamps + commit-message archaeology.
#
# Sprint 6.6.4: every dump is now encrypted at rest (gpg --symmetric,
# AES256, CPS_BACKUP_ENCRYPTION_PASSPHRASE in .env — see docs/ops/
# BACKUP.md) BEFORE anything else touches it; the plaintext .sql.gz
# never survives past that step. Retention is tiered — every backup
# from the last 30 days, plus one (the newest) per calendar month for
# the 12 months before that — not a flat N-day window. The encrypted
# copy is then offered to OCI Object Storage (CPS_BACKUP_CLOUD_* in
# .env — owner-provided, M3 in docs/prompts/sprint-6.6.md §4): unset
# today on this host, so the upload step logs a loud, clear warning
# and moves on — it deliberately never fails this script's own exit
# code, since scripts/deploy.sh depends on backup.sh succeeding before
# every single migration (apps.tenants.management.commands.migrate's
# own freshness guard) and a cloud outage/missing credential must
# never block a routine deploy over a copy that already exists, intact
# and encrypted, right here on disk.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="/opt/cps-backups"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
RAW_DUMP_FILE="$BACKUP_DIR/cps-db-$TIMESTAMP.sql.gz"
DUMP_FILE="$RAW_DUMP_FILE.gpg"
BACKUP_REASON="${1:-}"
OPS_LOG="$REPO_DIR/docs/ops/backups.log"

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

echo "[$(date -Iseconds)] Starting backup -> $RAW_DUMP_FILE"
# Sprint 6.6.0 (found while validating scripts/staging_refresh.sh): a
# plain pg_dump embeds `OWNER TO $POSTGRES_USER` / GRANT statements
# tied to THIS role's exact name — restoring onto a target whose own
# Postgres role has a different name (staging's "cps_staging", or any
# future production host's own) fails outright ("role ... does not
# exist") before a single row loads. --no-owner --no-privileges drops
# those statements; the restoring connection's own role becomes the
# owner instead, which is exactly what every restore here actually
# wants (this same fix is what scripts/restore_test.sh in 6.6.4 relies
# on too).
$COMPOSE exec -T postgres pg_dump --no-owner --no-privileges -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$RAW_DUMP_FILE"

if [ ! -s "$RAW_DUMP_FILE" ]; then
  echo "[$(date -Iseconds)] ERROR: backup file is empty — deleting and failing loudly." >&2
  rm -f "$RAW_DUMP_FILE"
  exit 1
fi
echo "[$(date -Iseconds)] Backup OK: $(du -h "$RAW_DUMP_FILE" | cut -f1)"

if [ -z "${CPS_BACKUP_ENCRYPTION_PASSPHRASE:-}" ]; then
  echo "[$(date -Iseconds)] ERROR: CPS_BACKUP_ENCRYPTION_PASSPHRASE is not set in .env — refusing to leave an unencrypted dump on disk. Generate one with: openssl rand -base64 48" >&2
  rm -f "$RAW_DUMP_FILE"
  exit 1
fi
echo "[$(date -Iseconds)] Encrypting -> $DUMP_FILE"
gpg --batch --yes --passphrase "$CPS_BACKUP_ENCRYPTION_PASSPHRASE" --symmetric --cipher-algo AES256 -o "$DUMP_FILE" "$RAW_DUMP_FILE"
rm -f "$RAW_DUMP_FILE"
echo "[$(date -Iseconds)] Encrypted OK: $(du -h "$DUMP_FILE" | cut -f1)"

GIT_HASH="$(git -C "$REPO_DIR" rev-parse --short HEAD 2>/dev/null || echo "unknown")"
mkdir -p "$(dirname "$OPS_LOG")"
printf '%s\t%s\t%s\t%s\n' "$(date -Iseconds)" "$GIT_HASH" "$(basename "$DUMP_FILE")" "$BACKUP_REASON" >> "$OPS_LOG"
echo "[$(date -Iseconds)] Logged to $OPS_LOG"

# Sprint 5.1 adds the MinIO attachments bucket here (mc mirror into
# $BACKUP_DIR/attachments/) once the Attachment model/storage exists —
# not yet, so there is nothing to sync today.

# Sprint 6.6.4 (M3, docs/prompts/sprint-6.6.md §4 — owner-provided,
# unset on this host today): upload the encrypted copy to OCI Object
# Storage (S3-compatible) via the backend image's own boto3 (already a
# dependency for MinIO/attachments) — no new host package needed, same
# `docker compose exec` pattern as the pg_dump step above. A missing
# config, or a genuine upload failure (network/credentials), is always
# a LOUD warning here, never a reason to fail this script's own exit
# code — see this file's own header comment for why.
if [ -n "${CPS_BACKUP_CLOUD_BUCKET:-}" ] && [ -n "${CPS_BACKUP_CLOUD_ENDPOINT_URL:-}" ] \
   && [ -n "${CPS_BACKUP_CLOUD_ACCESS_KEY:-}" ] && [ -n "${CPS_BACKUP_CLOUD_SECRET_KEY:-}" ]; then
  echo "[$(date -Iseconds)] Uploading $(basename "$DUMP_FILE") to OCI bucket $CPS_BACKUP_CLOUD_BUCKET"
  # /opt/cps-backups:ro is a permanent mount on the "backend" service
  # itself (infra/docker-compose.yml) — `exec` (unlike `run`) cannot add
  # an ad hoc mount to an already-running container, so this depends on
  # the NEXT `deploy.sh` having already recreated the container at
  # least once since that mount was added.
  if ! $COMPOSE exec -T \
    -e CPS_UPLOAD_BUCKET="$CPS_BACKUP_CLOUD_BUCKET" \
    -e CPS_UPLOAD_ENDPOINT_URL="$CPS_BACKUP_CLOUD_ENDPOINT_URL" \
    -e CPS_UPLOAD_ACCESS_KEY="$CPS_BACKUP_CLOUD_ACCESS_KEY" \
    -e CPS_UPLOAD_SECRET_KEY="$CPS_BACKUP_CLOUD_SECRET_KEY" \
    -e CPS_UPLOAD_REGION="${CPS_BACKUP_CLOUD_REGION:-us-ashburn-1}" \
    -e CPS_UPLOAD_FILE="/opt/cps-backups/$(basename "$DUMP_FILE")" \
    backend python3 /app/scripts/upload_backup_to_s3.py; then
    echo "[$(date -Iseconds)] WARNING: upload to OCI Object Storage failed — the local encrypted copy is unaffected; investigate before relying on the off-server copy." >&2
  else
    echo "[$(date -Iseconds)] Upload OK."
  fi
else
  echo "[$(date -Iseconds)] WARNING: CPS_BACKUP_CLOUD_BUCKET/ENDPOINT_URL/ACCESS_KEY/SECRET_KEY are not fully set — OCI Object Storage upload skipped (owner-provided, M3, docs/prompts/sprint-6.6.md §4). The local encrypted copy under $BACKUP_DIR is unaffected." >&2
fi

echo "[$(date -Iseconds)] Pruning: every backup from the last 30 days, plus one per calendar month for the 12 months before that"
"$REPO_DIR/scripts/prune_backups.sh" "$BACKUP_DIR"

echo "[$(date -Iseconds)] Done."
