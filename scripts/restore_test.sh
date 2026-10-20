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
# Block A (2026-10-20): attachments. A restored row pointing at a missing
# object is the failure this guards against, so the verdict now also needs
# the bytes back: the dump's paired attachments manifest (written by
# scripts/backup_attachments.sh) is restored into a THROWAWAY MinIO, and a
# THROWAWAY backend — pointed only at the restored database and that MinIO,
# never at the live ones — downloads every attachment row through the
# app's own signed-link view and compares each body with the row's sha256.
# Rows the app withholds by design (scan_status not clean/skipped) are read
# through the app's storage layer instead. FAIL on any mismatch or missing
# object, and FAIL if not one row was downloadable (nothing proven). Both
# the dump and the manifest must also pass the source checks of
# scripts/restore_lib.sh: recorded as taken from the environment tested.
#
# Usage: scripts/restore_test.sh [--target live|dev|staging]   (default live — cron's)
# Suggested monthly root cron (see docs/ops/BACKUP.md):
#   0 4 1 * * /opt/cps/scripts/restore_test.sh >> /var/log/cps-restore-test.log 2>&1

TARGET="live"
if [ "${1:-}" = "--target" ]; then TARGET="${2:?usage: scripts/restore_test.sh [--target live|dev|staging]}"; shift 2; fi
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="/opt/cps-backups"
[ "$TARGET" = "live" ] || BACKUP_DIR="/opt/cps-backups/$TARGET"
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
[ "$TARGET" != "staging" ] || source "$REPO_DIR/.env.staging"
set +a
# shellcheck source=restore_lib.sh
source "$REPO_DIR/scripts/restore_lib.sh"
COMPOSE="$(cps_env_compose "$TARGET")" || exit 1
cd "$REPO_DIR/infra"
RT_MINIO="cps-restore-test-minio-$$"

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
  docker rm -f "$RT_MINIO" > /dev/null 2>&1 || true
}
trap cleanup EXIT

LATEST_BACKUP="$(find "$BACKUP_DIR" -maxdepth 1 -name 'cps-db-*.sql.gz.gpg' -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)"
[ -n "$LATEST_BACKUP" ] || fail "no cps-db-*.sql.gz.gpg backup found in $BACKUP_DIR"
BACKUP_NAME="$(basename "$LATEST_BACKUP")"
log "using backup: $BACKUP_NAME"

[ -n "${CPS_BACKUP_ENCRYPTION_PASSPHRASE:-}" ] || fail "CPS_BACKUP_ENCRYPTION_PASSPHRASE is not set in .env"

DUMP_TS="${BACKUP_NAME#cps-db-}"
DUMP_TS="${DUMP_TS%.sql.gz.gpg}"
MANIFEST="$BACKUP_DIR/attachments/manifests/attachments-$DUMP_TS.manifest.gpg"
SOURCE_CHECK="$(cps_require_dump_from "$LATEST_BACKUP" "$TARGET" 2>&1)" || fail "$SOURCE_CHECK"
log "$SOURCE_CHECK"
[ -f "$MANIFEST" ] || fail "no attachments manifest paired with $BACKUP_NAME (expected $MANIFEST) — the attachments of this backup cannot be restored"
SOURCE_CHECK="$(cps_require_manifest_from "$MANIFEST" "$TARGET" "$LATEST_BACKUP" 2>&1)" || fail "$SOURCE_CHECK"
log "$SOURCE_CHECK"

cleanup  # in case a previous run was interrupted before its own cleanup ran

log "creating throwaway database $RESTORE_TEST_DB"
$COMPOSE exec -T postgres createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" "$RESTORE_TEST_DB" \
  || fail "could not create $RESTORE_TEST_DB"

log "decrypting and restoring into it"
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
if ! gpg --batch --yes --passphrase-file <(printf '%s' "$CPS_BACKUP_ENCRYPTION_PASSPHRASE") --decrypt "$LATEST_BACKUP" 2>/dev/null \
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
# Rule 50 (block A, 2026-10-20): the URL carries the database password, so it
# travels by NAME — `-e DATABASE_URL` with no value makes compose read it from
# its own environment, set by the prefix assignment. Until today both calls
# below had `-e DATABASE_URL="$TEST_DATABASE_URL"`, the password readable in
# `ps` on live's monthly cron path; the rule-50 guard's pattern could not see
# it (a URL, not a *PASSWORD* name).
if ! DATABASE_URL="$TEST_DATABASE_URL" $COMPOSE exec -T -e DATABASE_URL backend python manage.py check; then
  fail "manage.py check failed against the restored database"
fi

# Sprint 7.0.2 follow-up (docs/SYSTEM_ANALYSIS.md §11, 2026-10-04): both
# counts below used to include archived tenants with no exclusion at
# all. A historical audit found 19 archived smoke-* tenants silently
# carrying 57 POSTED, never-reversed JournalEntry rows — on the same
# day this script last ran, those accounted for 58 of 87 (two-thirds)
# of the platform-wide "posted" count, with zero bearing on whether a
# backup of the LIVE, in-use data actually restores correctly. The fix
# belongs in the metric, not the data (the 57 rows are deliberately
# left as documented, inert debt — see docs/ops/archived_tenant_debt.md):
# every cross-tenant aggregate here now excludes archived tenants, so
# this check reflects restore health of live tenants, not a count
# inflated by dead test tenants nobody will ever look at again.
RESTORED_TENANTS="$($COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d "$RESTORE_TEST_DB" -t -A -c \
  "SELECT count(*) FROM tenants_tenant WHERE status != 'archived';" | tr -d '[:space:]')"
LIVE_TENANTS="$($COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -A -c \
  "SELECT count(*) FROM tenants_tenant WHERE status != 'archived';" | tr -d '[:space:]')"

# Sprint 7.0.3: the posted-entries count is exactly what
# apps.accounting.services.unreversed_posted_entries(tenant) means
# ("still open, not yet reversed") summed across live tenants — call
# it through the backend's own Django ORM instead of re-deriving the
# same `status='posted'` filter a third time in raw SQL (this file,
# the audit, and a management command all drifted on this once; see
# docs/SYSTEM_ANALYSIS.md §11, 2026-10-04 follow-up).
POSTED_COUNT_PY='
from apps.tenants.models import Tenant
from apps.accounting.services import unreversed_posted_entries
total = sum(unreversed_posted_entries(t).count() for t in Tenant.objects.exclude(status="archived"))
print(f"RESULT:{total}")
'
RESTORED_POSTED="$(DATABASE_URL="$TEST_DATABASE_URL" $COMPOSE exec -T -e DATABASE_URL backend python manage.py shell -c "$POSTED_COUNT_PY" \
  | sed -n 's/^RESULT://p' | tr -d '[:space:]')"
LIVE_POSTED="$($COMPOSE exec -T backend python manage.py shell -c "$POSTED_COUNT_PY" \
  | sed -n 's/^RESULT://p' | tr -d '[:space:]')"

log "tenants: restored=$RESTORED_TENANTS live=$LIVE_TENANTS | posted entries: restored=$RESTORED_POSTED live=$LIVE_POSTED"

[ "${RESTORED_TENANTS:-0}" -gt 0 ] || fail "restored database has zero tenants — treating as a corrupt/empty restore"

if [ "${LIVE_TENANTS:-0}" -gt 0 ]; then
  BELOW_MIN="$(awk -v r="$RESTORED_TENANTS" -v l="$LIVE_TENANTS" -v m="$MIN_FRACTION_OF_LIVE" 'BEGIN { print (r < l * m) ? 1 : 0 }')"
  if [ "$BELOW_MIN" = "1" ]; then
    fail "restored tenant count ($RESTORED_TENANTS) is suspiciously low next to live's ($LIVE_TENANTS) — possible truncated/corrupt backup"
  fi
fi

# --- Attachments: restore into a throwaway MinIO, download through the app.
NETWORK="$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$($COMPOSE ps -q postgres)" | cut -d' ' -f1)"
MINIO_IMAGE="$(docker inspect -f '{{.Config.Image}}' "$($COMPOSE ps -q minio)")"
BACKEND_ID="$($COMPOSE ps -q backend)"
BACKEND_IMAGE="$(docker inspect -f '{{.Config.Image}}' "$BACKEND_ID")"
# Fresh credentials for the throwaway MinIO, by name only (rule 50).
export MINIO_ROOT_USER="rt$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n')"
export MINIO_ROOT_PASSWORD="$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')"
log "starting throwaway MinIO $RT_MINIO ($MINIO_IMAGE) on $NETWORK"
docker run -d --name "$RT_MINIO" --network "$NETWORK" -e MINIO_ROOT_USER -e MINIO_ROOT_PASSWORD \
  "$MINIO_IMAGE" server /data > /dev/null || fail "could not start a throwaway MinIO"
for _ in $(seq 1 30); do
  docker exec "$RT_MINIO" sh -c "$CPS_MC_ENV; mc ready m" > /dev/null 2>&1 && break
  sleep 1
done
docker exec -e B="$MINIO_BUCKET" "$RT_MINIO" sh -c "$CPS_MC_ENV; mc mb \"m/\$B\" > /dev/null" || fail "throwaway MinIO never came up"
log "restoring attachments from $(basename "$MANIFEST")"
ATT_RESTORE="$(cps_restore_attachments "$MANIFEST" "$BACKUP_DIR/attachments" "$RT_MINIO" "$MINIO_BUCKET" 2>&1)" \
  || fail "attachment restore: $(echo "$ATT_RESTORE" | tr '\n' ' ')"
log "attachments restored: $(echo "$ATT_RESTORE" | tail -1)"

DOWNLOAD_PY='
import hashlib
from django.conf import settings
from django.test import Client
from apps.attachments.models import Attachment
from apps.attachments.services import sign_link
settings.ALLOWED_HOSTS = ["*"]
client = Client()
downloaded = verified = bad = 0
for a in Attachment.objects.order_by("file"):
    body = b""
    try:
        if a.scan_status in (Attachment.ScanStatus.CLEAN, Attachment.ScanStatus.SKIPPED):
            r = client.get(f"/api/attachments/{a.id}/download/", {"token": sign_link(a.id)})
            body = b"".join(r.streaming_content) if getattr(r, "streaming", False) else r.content
            good = r.status_code == 200 and hashlib.sha256(body).hexdigest() == a.sha256
            how = f"downloaded through the app, HTTP {r.status_code}"
            downloaded += good
        else:
            with a.file.open("rb") as f:
                body = f.read()
            good = hashlib.sha256(body).hexdigest() == a.sha256
            how = f"read through the app storage (scan_status {a.scan_status}: withheld from download by design)"
            verified += good
    except Exception as exc:  # a row whose object is gone: name it, keep going
        good, how = False, f"NOT READABLE: {type(exc).__name__}: {str(exc)[:120]}"
    bad += not good
    print(("ROW OK   " if good else "ROW BAD  ") + f"{a.file.name} [{a.status}] {len(body)} bytes, {how}")
print(f"RESULT:{downloaded}:{verified}:{bad}")
'
log "downloading every attachment through a throwaway backend ($BACKEND_IMAGE) on the restored data"
DOWNLOAD_OUT="$(docker run --rm --network "$NETWORK" --env-file <(
    docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$BACKEND_ID" \
      | grep -vE '^(DATABASE_URL|PLATFORM_DATABASE_URL|MINIO_ENDPOINT_URL|MINIO_ACCESS_KEY|MINIO_SECRET_KEY|ATTACHMENT_STORAGE_BACKEND)='
    printf 'DATABASE_URL=%s\nPLATFORM_DATABASE_URL=%s\n' "$TEST_DATABASE_URL" "$TEST_DATABASE_URL"
    printf 'MINIO_ENDPOINT_URL=http://%s:9000\nMINIO_ACCESS_KEY=%s\nMINIO_SECRET_KEY=%s\nATTACHMENT_STORAGE_BACKEND=s3\n' \
      "$RT_MINIO" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
  ) "$BACKEND_IMAGE" python manage.py shell -c "$DOWNLOAD_PY" 2>&1)" || fail "the throwaway backend failed: $(echo "$DOWNLOAD_OUT" | tail -5 | tr '\n' ' ')"
echo "$DOWNLOAD_OUT" | grep '^ROW '
RESULT_LINE="$(echo "$DOWNLOAD_OUT" | sed -n 's/^RESULT://p')"
IFS=: read -r ATT_DOWNLOADED ATT_VERIFIED ATT_BAD <<< "$RESULT_LINE"
ATT_DETAIL="attachments: ${ATT_DOWNLOADED:-?} downloaded byte-identical, ${ATT_VERIFIED:-?} verified via storage, ${ATT_BAD:-?} bad ($(echo "$ATT_RESTORE" | tail -1))"
log "$ATT_DETAIL"
[ "${ATT_BAD:-1}" = "0" ] || fail "$ATT_DETAIL"
[ "${ATT_DOWNLOADED:-0}" -gt 0 ] || fail "$ATT_DETAIL — not one attachment downloadable after the restore, so nothing is proven"

log "OK"
record_result "OK" "$BACKUP_NAME" "$RESTORED_TENANTS" "$LIVE_TENANTS" "$RESTORED_POSTED" "$LIVE_POSTED" "$ATT_DETAIL"
