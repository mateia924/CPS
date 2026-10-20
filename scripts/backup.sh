#!/usr/bin/env bash
set -euo pipefail
# Block A (2026-10-20): every file and directory this creates is root-only
# (dumps were 0644 inside the 0700 directory until today).
umask 077

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

# Pre-deploy 1 (2026-10-17): --target dev|staging|live (default live —
# root cron and every existing caller keep their exact behavior). Until
# now this script could only ever dump live, so migrating dev or staging
# meant either backing up live to satisfy the migrate guard (which
# checked a timestamp, not a database) or CPS_SKIP_BACKUP_GUARD=1 — and
# a guard every developer has to skip teaches everyone to skip it. Each
# target dumps its own compose project's postgres, and every backups.log
# line now ends with db=<host>/<name>#<system_identifier>, read from the
# very database being dumped, in the same `exec` that dumps it — the
# identity apps.tenants's migrate guard matches against its own
# connection. Host and name alone would not do: live and dev are both
# postgres/cps; the cluster's system_identifier (fixed at initdb) is what
# separates them. dev/staging dumps go to their own subdirectory, so
# nothing that picks "the latest cps-db-*" in $BACKUP_DIR (staging_
# refresh.sh's restore, restore_test.sh) can ever pick one up, and are
# never uploaded off-server: a working copy, not the insurance policy.
#
# Usage: scripts/backup.sh [--target dev|staging|live] ["reason"]

TARGET="live"
if [ "${1:-}" = "--target" ]; then
  TARGET="${2:?usage: scripts/backup.sh [--target dev|staging|live] [\"reason\"]}"
  shift 2
fi
case "$TARGET" in
  live|dev|staging) ;;
  *) echo "ERROR: unknown --target \"$TARGET\" (expected dev, staging or live)." >&2; exit 1 ;;
esac

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# CPS_BACKUP_ROOT exists for tests only (backend/tests/test_backup_attachments.py
# runs this script against a scratch directory); cron never sets it.
BACKUP_ROOT="${CPS_BACKUP_ROOT:-/opt/cps-backups}"
BACKUP_DIR="$BACKUP_ROOT"
[ "$TARGET" = "live" ] || BACKUP_DIR="$BACKUP_ROOT/$TARGET"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
DUMP_FILE="$BACKUP_DIR/cps-db-$TIMESTAMP.sql.gz.gpg"
DUMP_PART="$DUMP_FILE.part"
BACKUP_REASON="${1:-}"
OPS_LOG="$REPO_DIR/docs/ops/backups.log"

# Outside every container, root-only — these are the only real copies
# of tenant data (docs/SYSTEM_ANALYSIS.md rule 10: never delete a
# database/volume without explicit permission; a backup is the
# insurance policy against ever needing to test that rule under duress).
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_ROOT" "$BACKUP_DIR"

# The encryption passphrase always comes from .env (staging_refresh.sh's
# own rule): kept aside before .env.staging can shadow anything.
set -a
source "$REPO_DIR/.env"
set +a
PASSPHRASE="${CPS_BACKUP_ENCRYPTION_PASSPHRASE:-}"
case "$TARGET" in
  live)
    COMPOSE="docker compose --env-file $REPO_DIR/.env" ;;
  dev)
    COMPOSE="docker compose -p cps-dev --env-file $REPO_DIR/.env -f docker-compose.yml -f docker-compose.dev.yml" ;;
  staging)
    [ -f "$REPO_DIR/.env.staging" ] || { echo "ERROR: $REPO_DIR/.env.staging not found." >&2; exit 1; }
    set -a
    source "$REPO_DIR/.env.staging"
    set +a
    COMPOSE="docker compose -p cps-staging --env-file $REPO_DIR/.env.staging -f docker-compose.yml -f docker-compose.staging.yml" ;;
esac
cd "$REPO_DIR/infra"

# "postgres" is the compose service every Django DATABASE_URL here names
# as its host (infra/docker-compose.yml) — the only host this script can
# dump. Read before the dump: a database that cannot say who it is gets
# no backup line, so it can never satisfy the guard by accident.
DB_SYSTEM_ID="$($COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc \
  "SELECT system_identifier FROM pg_control_system()" | tr -d '\r')"
case "$DB_SYSTEM_ID" in
  ''|*[!0-9]*) echo "ERROR: could not read $TARGET's system_identifier (got \"$DB_SYSTEM_ID\") — refusing to log a backup with no database identity." >&2; exit 1 ;;
esac
DB_IDENTITY="postgres/$POSTGRES_DB#$DB_SYSTEM_ID"
echo "[$(date -Iseconds)] Target: $TARGET ($DB_IDENTITY)"

if [ -z "$PASSPHRASE" ]; then
  echo "[$(date -Iseconds)] ERROR: CPS_BACKUP_ENCRYPTION_PASSPHRASE is not set in .env — refusing to take a backup that would sit on disk unencrypted. Generate one with: openssl rand -base64 48" >&2
  exit 1
fi

# Block A (2026-10-20): the dump is streamed pg_dump | gzip | gpg, so the
# plaintext never touches the disk. Until today it was written to
# cps-db-<ts>.sql.gz first and encrypted afterwards: a gpg failure, or the
# run killed in between, left a full plaintext dump of every tenant behind
# (set -e exits before the rm), and prune_backups.sh, matching only .gpg,
# would never have removed it. Now the only thing a dying run can leave is
# the ENCRYPTED partial $DUMP_PART — removed by the EXIT trap on any exit
# bash survives to run it (errors, INT/TERM/HUP routed through it), and by
# prune_backups.sh after a SIGKILL. backend/tests/test_backup_plaintext.py
# kills a run mid-dump and checks no plaintext survives.
trap 'command rm -f "$DUMP_PART"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

echo "[$(date -Iseconds)] Starting backup -> $DUMP_FILE (pg_dump | gzip | gpg: never on disk in plaintext)"
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
$COMPOSE exec -T postgres pg_dump --no-owner --no-privileges -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip \
  | gpg --batch --yes --passphrase-file <(printf '%s' "$PASSPHRASE") --symmetric --cipher-algo AES256 -o "$DUMP_PART"

# An empty dump is a failure: check the content through the ciphertext.
if [ "$(gpg --quiet --batch --passphrase-file <(printf '%s' "$PASSPHRASE") --decrypt "$DUMP_PART" 2>/dev/null | gunzip -c | head -c 1024 | wc -c)" -eq 0 ]; then
  echo "[$(date -Iseconds)] ERROR: the dump is empty — failing loudly (the encrypted partial is removed)." >&2
  exit 1
fi
mv "$DUMP_PART" "$DUMP_FILE"
echo "[$(date -Iseconds)] Backup OK, encrypted: $(du -h "$DUMP_FILE" | cut -f1)"

GIT_HASH="$(git -C "$REPO_DIR" rev-parse --short HEAD 2>/dev/null || echo "unknown")"
mkdir -p "$(dirname "$OPS_LOG")"
LOGGED_FILE="$(basename "$DUMP_FILE")"
[ "$TARGET" = "live" ] || LOGGED_FILE="$TARGET/$LOGGED_FILE"
printf '%s\t%s\t%s\t%s\tdb=%s\n' "$(date -Iseconds)" "$GIT_HASH" "$LOGGED_FILE" "$BACKUP_REASON" "$DB_IDENTITY" >> "$OPS_LOG"
echo "[$(date -Iseconds)] Logged to $OPS_LOG"

# Block A (2026-10-20): the attachments bucket, per object, encrypted —
# scripts/backup_attachments.sh. It runs only here, after the database dump
# is encrypted, logged and pruned, and ONLY inside `if !`: a condition is
# exempt from `set -e`, so whatever it does — MinIO unreachable, wrong
# credentials, a missing object, a hang cut short by `timeout` — this
# script's exit code and the database's backups.log line above stay
# exactly what they would have been without it. The attachment step writes
# its own backups.log line, FAILED included. Never call it bare.
backup_attachments() {
  local logged_prefix=""
  [ "$TARGET" = "live" ] || logged_prefix="$TARGET/"
  if ! CPS_ATT_STORE="$BACKUP_DIR/attachments" CPS_ATT_TIMESTAMP="$TIMESTAMP" \
       CPS_ATT_PAIRS="$(basename "$DUMP_FILE")" CPS_ATT_REASON="$BACKUP_REASON" CPS_ATT_GIT="$GIT_HASH" \
       CPS_ATT_OPS_LOG="$OPS_LOG" CPS_ATT_LOGGED_PREFIX="$logged_prefix" COMPOSE="$COMPOSE" PASSPHRASE="$PASSPHRASE" \
       timeout "${CPS_ATT_TIMEOUT:-1800}" "$REPO_DIR/scripts/backup_attachments.sh"; then
    echo "[$(date -Iseconds)] WARNING: the attachment backup did not complete — the database backup above is unaffected and logged. See the attachments line in $OPS_LOG." >&2
  fi
}

if [ "$TARGET" != "live" ]; then
  echo "[$(date -Iseconds)] $TARGET dump: local copy only, never uploaded off-server."
  "$REPO_DIR/scripts/prune_backups.sh" "$BACKUP_DIR"
  backup_attachments
  echo "[$(date -Iseconds)] Done."
  exit 0
fi

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
  # Pre-deploy 5 (rule 50): the two keys travel by NAME only. `-e NAME`
  # with no `=` makes compose read the value from its own environment,
  # set here by the prefix assignments — an environment, unlike argv, is
  # not readable in `ps` by other users. Until this block the secret key
  # sat in `docker compose exec ... -e CPS_UPLOAD_SECRET_KEY=<value>`
  # every night at 03:00 on live. Never write `-e NAME="$VALUE"` back.
  if ! CPS_UPLOAD_ACCESS_KEY="$UPLOAD_ACCESS_KEY" CPS_UPLOAD_SECRET_KEY="$UPLOAD_SECRET_KEY" \
    $COMPOSE exec -T \
    -e CPS_UPLOAD_BUCKET="$UPLOAD_BUCKET" \
    -e CPS_UPLOAD_ENDPOINT_URL="$UPLOAD_ENDPOINT" \
    -e CPS_UPLOAD_ACCESS_KEY \
    -e CPS_UPLOAD_SECRET_KEY \
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

backup_attachments
echo "[$(date -Iseconds)] Done."
