#!/usr/bin/env bash
set -uo pipefail

# Block A (2026-10-20): the attachments bucket in the nightly backup. Until
# today backup.sh never copied it — every source document on live existed
# in exactly one place, and a database restore would have brought back rows
# pointing at objects that might no longer exist.
#
# Called ONLY by scripts/backup.sh, after the database dump is encrypted and
# its backups.log line written, as
#     if ! timeout ... scripts/backup_attachments.sh; then <warning>; fi
# so nothing here can fail, delay past the timeout, or change the exit code
# of the database backup (backend/tests/test_backup_attachments.py proves
# it with MinIO unreachable). Everything arrives in the environment from
# backup.sh: CPS_ATT_* below, COMPOSE, PASSPHRASE, POSTGRES_USER/DB and
# MINIO_BUCKET.
#
# Shape (owner decision 2026-10-20: per-object encryption):
#   - the keys come from the DATABASE, not a bucket listing: every row of
#     attachments_attachment, with no WHERE — active, voided and superseded
#     versions, any scan state, archived tenants included. An accounting
#     system keeps voided documents; a filter on status would let every
#     voided attachment fall out of the backup unnoticed. Orphan objects
#     with no row (test litter) are skipped by construction. Read right
#     after the dump, so the list is a superset of the dump's rows (rows
#     are never deleted).
#   - each object not yet in the store is streamed out of MinIO, encrypted
#     (gpg AES256, the dump's passphrase) to objects/<key>.gpg, decrypted
#     back and its sha256 compared with the row's before it is kept. A
#     mismatch is reported and nothing is written; an object already in the
#     store is never replaced — nothing on the source side can overwrite or
#     remove a backed-up copy.
#   - one encrypted manifest per run, manifests/attachments-<ts>.manifest.gpg:
#     a header (source identity, the paired dump) and one line per row with
#     its sha256, size, status and what happened to it.
#   - one backups.log line per run, FAILED included, carrying
#     minio=minio/<bucket>#<deploymentID> — MinIO's own deployment ID
#     (.minio.sys/format.json, written once when the data directory is
#     initialised) — and pairs=<the dump it belongs with>. No db= field, so
#     the migrate guard never mistakes it for a database backup.
#
# Exit 0 only if every referenced object is in the store and matches.

# Everything this writes is root-only, every directory level included.
umask 077
STORE="${CPS_ATT_STORE:?}"
OBJECTS="$STORE/objects"
MANIFESTS="$STORE/manifests"
MANIFEST_NAME="attachments-${CPS_ATT_TIMESTAMP:?}.manifest.gpg"
IDENTITY="unknown"
REFS=0 NEW=0 KEPT=0 BYTES=0 MISSING=0 MISMATCH=0
REFS_FILE="" MANIFEST_PLAIN=""

log_line() {
  printf '%s\t%s\t%s\t%s\tminio=%s\tpairs=%s\trefs=%s\tnew=%s\tkept=%s\tbytes=%s\tmissing=%s\tmismatch=%s\tstatus=%s\n' \
    "$(date -Iseconds)" "${CPS_ATT_GIT:-unknown}" "${CPS_ATT_LOGGED_PREFIX:-}attachments/manifests/$MANIFEST_NAME" \
    "${CPS_ATT_REASON:-}" "$IDENTITY" "${CPS_ATT_PAIRS:?}" "$REFS" "$NEW" "$KEPT" "$BYTES" "$MISSING" "$MISMATCH" "$1" \
    >> "${CPS_ATT_OPS_LOG:?}"
}

fail() {
  echo "[$(date -Iseconds)] ATTACHMENTS FAILED: $1" >&2
  log_line "FAILED:$1"
  exit 1
}

cleanup() {
  command rm -f "$REFS_FILE" "$MANIFEST_PLAIN" 2>/dev/null
  find "$OBJECTS" -name '*.part' -type f -delete 2>/dev/null
}
trap cleanup EXIT
# backup.sh runs this under `timeout`: a TERM still leaves a FAILED line.
trap 'fail "terminated"' TERM INT

# Rule 50: the passphrase reaches gpg through a file descriptor written by
# the bash BUILTIN printf — never argv (same as backup.sh; see its comment).
encrypt_to() { gpg --batch --yes --passphrase-file <(printf '%s' "$PASSPHRASE") --symmetric --cipher-algo AES256 -o "$1"; }
decrypt() { gpg --batch --quiet --passphrase-file <(printf '%s' "$PASSPHRASE") --decrypt "$1"; }

[ -n "${PASSPHRASE:-}" ] || fail "no-passphrase"
mkdir -p "$OBJECTS" "$MANIFESTS" 2>/dev/null && chmod 700 "$STORE" "$OBJECTS" "$MANIFESTS" || fail "store-not-writable"

# The MinIO root credentials stay inside the minio container: MC_HOST_*
# is built there from its own environment, so no key is ever on a command
# line, here or in the container.
MC_ENV='export MC_HOST_m="http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@localhost:9000"'
DEPLOYMENT_ID="$($COMPOSE exec -T minio sh -c "$MC_ENV; mc admin info --json m" </dev/null 2>/dev/null \
  | python3 -c 'import json, sys; print(json.load(sys.stdin)["info"]["deploymentID"])' 2>/dev/null)"
case "$DEPLOYMENT_ID" in
  [0-9a-f]*-*-*-*-*) ;;
  *) fail "minio-unreachable" ;;
esac
IDENTITY="minio/${MINIO_BUCKET:?}#$DEPLOYMENT_ID"
echo "[$(date -Iseconds)] Attachments: source $IDENTITY, paired with ${CPS_ATT_PAIRS}"

REFS_FILE="$(mktemp -p "$STORE" .refs.XXXXXX)" || fail "store-not-writable"
$COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -F "$(printf '\t')" -c \
  "SELECT file, sha256, size, status FROM attachments_attachment ORDER BY file" </dev/null > "$REFS_FILE" \
  || fail "refs-query"

MANIFEST_PLAIN="$(mktemp -p "$STORE" .manifest.XXXXXX)" || fail "store-not-writable"
printf '#cps-attachments-manifest\tv1\n#minio\t%s\n#pairs\t%s\n#taken\t%s\n' \
  "$IDENTITY" "$CPS_ATT_PAIRS" "$(date -Iseconds)" > "$MANIFEST_PLAIN"

while IFS="$(printf '\t')" read -r key sha size status; do
  [ -n "$key" ] || continue
  REFS=$((REFS + 1))
  case "$key" in
    /*|*..*|*"$(printf '\t')"*) state="invalid-key"; MISMATCH=$((MISMATCH + 1)) ;;
    *)
      dest="$OBJECTS/$key.gpg"
      if [ -f "$dest" ]; then
        state="kept"; KEPT=$((KEPT + 1))
      else
        mkdir -p "$(dirname "$dest")"
        part="$dest.part"
        if $COMPOSE exec -T -e K="$key" -e B="$MINIO_BUCKET" minio sh -c "$MC_ENV; mc cat \"m/\$B/\$K\"" </dev/null 2>/dev/null \
             | encrypt_to "$part" \
           && [ "$(decrypt "$part" | sha256sum | cut -d' ' -f1)" = "$sha" ]; then
          mv "$part" "$dest"
          state="new"; NEW=$((NEW + 1)); BYTES=$((BYTES + size))
        elif [ -s "$part" ] && [ "$(decrypt "$part" | head -c 1 | wc -c)" -gt 0 ]; then
          state="mismatch"; MISMATCH=$((MISMATCH + 1))
          echo "[$(date -Iseconds)] Attachments: sha256 MISMATCH, not stored: $key" >&2
        else
          state="missing"; MISSING=$((MISSING + 1))
          echo "[$(date -Iseconds)] Attachments: object MISSING from the bucket: $key" >&2
        fi
        command rm -f "$part"
      fi
      ;;
  esac
  printf '%s\t%s\t%s\t%s\t%s\n' "$key" "$sha" "$size" "$status" "$state" >> "$MANIFEST_PLAIN"
done < "$REFS_FILE"

encrypt_to "$MANIFESTS/$MANIFEST_NAME" < "$MANIFEST_PLAIN" || fail "manifest-write"
chmod 600 "$MANIFESTS/$MANIFEST_NAME"

if [ "$MISSING" -gt 0 ] || [ "$MISMATCH" -gt 0 ]; then
  fail "missing=$MISSING,mismatch=$MISMATCH"
fi
log_line "OK"
echo "[$(date -Iseconds)] Attachments OK: $REFS referenced, $NEW new ($BYTES bytes), $KEPT already stored."
