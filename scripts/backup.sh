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
# copy is then offered to a cloud/off-server target — OCI Object
# Storage once the owner delivers real credentials (M3, docs/prompts/
# sprint-6.6.md §4), MinIO as the interim target until then ("Option
# 1", sprint-6.6.md v1.1 §6.1 — see the upload section below for the
# full reasoning). A missing target or a failed upload is a LOUD
# warning that still lets this script exit 0 in dev/staging (scripts/
# deploy.sh depends on backup.sh succeeding before every single
# migration, apps.tenants.management.commands.migrate's own freshness
# guard, and a cloud outage/missing credential must never block a
# routine deploy over a copy that already exists, intact and
# encrypted, right here on disk) — but a hard failure (non-zero exit)
# when CPS_ENVIRONMENT=production, where backup durability stops
# being optional.

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

# Sprint 6.6.4 "Option 1" (sprint-6.6.md v1.1 §6.1): OCI Object
# Storage (M3, docs/prompts/sprint-6.6.md §4 — owner-provided, unset
# on this host today) wins automatically the moment all four
# CPS_BACKUP_CLOUD_* vars are set. Until then, MinIO — already
# running, already has real credentials in every environment this
# project has — is the INTERIM upload target: not genuine off-site
# protection (same host, same disk failure takes both out), but it
# exercises the real upload code path now instead of leaving it fully
# untested until M3 arrives, and survives an accidental deletion of
# /opt/cps-backups specifically. Severity differs by environment: a
# missing target or a genuine upload failure is a LOUD warning in
# dev/staging (never blocks scripts/deploy.sh, which depends on this
# script's own exit code before every migration) but a hard failure
# in production — see this file's own header for the dev/staging
# reasoning, which still applies there unchanged.
UPLOAD_ENDPOINT="" UPLOAD_BUCKET="" UPLOAD_ACCESS_KEY="" UPLOAD_SECRET_KEY="" UPLOAD_REGION="" UPLOAD_ENSURE_BUCKET="0" UPLOAD_LABEL=""
if [ -n "${CPS_BACKUP_CLOUD_BUCKET:-}" ] && [ -n "${CPS_BACKUP_CLOUD_ENDPOINT_URL:-}" ] \
   && [ -n "${CPS_BACKUP_CLOUD_ACCESS_KEY:-}" ] && [ -n "${CPS_BACKUP_CLOUD_SECRET_KEY:-}" ]; then
  UPLOAD_ENDPOINT="$CPS_BACKUP_CLOUD_ENDPOINT_URL"
  UPLOAD_BUCKET="$CPS_BACKUP_CLOUD_BUCKET"
  UPLOAD_ACCESS_KEY="$CPS_BACKUP_CLOUD_ACCESS_KEY"
  UPLOAD_SECRET_KEY="$CPS_BACKUP_CLOUD_SECRET_KEY"
  UPLOAD_REGION="${CPS_BACKUP_CLOUD_REGION:-us-ashburn-1}"
  UPLOAD_LABEL="OCI bucket $UPLOAD_BUCKET"
elif [ -n "${MINIO_ACCESS_KEY:-}" ] && [ -n "${MINIO_SECRET_KEY:-}" ]; then
  UPLOAD_ENDPOINT="${MINIO_ENDPOINT_URL:-http://minio:9000}"
  UPLOAD_BUCKET="${CPS_BACKUP_MINIO_BUCKET:-cps-backups-interim}"
  UPLOAD_ACCESS_KEY="$MINIO_ACCESS_KEY"
  UPLOAD_SECRET_KEY="$MINIO_SECRET_KEY"
  UPLOAD_REGION="us-east-1"
  UPLOAD_ENSURE_BUCKET="1"
  UPLOAD_LABEL="MinIO bucket $UPLOAD_BUCKET (مؤقت — بانتظار M3، ليست حماية off-site حقيقية — نفس الخادم)"
fi

UPLOAD_OK=1
if [ -n "$UPLOAD_ENDPOINT" ]; then
  echo "[$(date -Iseconds)] Uploading $(basename "$DUMP_FILE") to $UPLOAD_LABEL"
  # /opt/cps-backups:ro is a permanent mount on the "backend" service
  # itself (infra/docker-compose.yml) — `exec` (unlike `run`) cannot add
  # an ad hoc mount to an already-running container, so this depends on
  # the NEXT `deploy.sh` having already recreated the container at
  # least once since that mount was added.
  if ! $COMPOSE exec -T \
    -e CPS_UPLOAD_BUCKET="$UPLOAD_BUCKET" \
    -e CPS_UPLOAD_ENDPOINT_URL="$UPLOAD_ENDPOINT" \
    -e CPS_UPLOAD_ACCESS_KEY="$UPLOAD_ACCESS_KEY" \
    -e CPS_UPLOAD_SECRET_KEY="$UPLOAD_SECRET_KEY" \
    -e CPS_UPLOAD_REGION="$UPLOAD_REGION" \
    -e CPS_UPLOAD_ENSURE_BUCKET="$UPLOAD_ENSURE_BUCKET" \
    -e CPS_UPLOAD_FILE="/opt/cps-backups/$(basename "$DUMP_FILE")" \
    backend python3 /app/scripts/upload_backup_to_s3.py; then
    UPLOAD_OK=0
    echo "[$(date -Iseconds)] WARNING: upload to $UPLOAD_LABEL failed — the local encrypted copy is unaffected; investigate before relying on the off-server copy." >&2
  else
    echo "[$(date -Iseconds)] Upload OK."
  fi
else
  UPLOAD_OK=0
  echo "[$(date -Iseconds)] WARNING: no upload target configured at all — neither OCI (CPS_BACKUP_CLOUD_*, M3) nor MinIO (MINIO_ACCESS_KEY/SECRET_KEY) credentials are set. The local encrypted copy under $BACKUP_DIR is unaffected." >&2
fi

if [ "$UPLOAD_OK" = "0" ] && [ "${CPS_ENVIRONMENT:-}" = "production" ]; then
  echo "[$(date -Iseconds)] ERROR: backup durability is not optional in production — refusing to continue with no working off-server copy." >&2
  exit 1
fi

echo "[$(date -Iseconds)] Pruning: every backup from the last 30 days, plus one per calendar month for the 12 months before that"
"$REPO_DIR/scripts/prune_backups.sh" "$BACKUP_DIR"

echo "[$(date -Iseconds)] Done."
