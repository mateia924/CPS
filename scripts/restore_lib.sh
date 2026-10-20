# shellcheck shell=bash
# Block A (2026-10-20): what scripts/restore.sh and scripts/restore_test.sh
# share — finding out where a backup came from, refusing it when that is not
# the source the operator named, and restoring a manifest's attachments.
#
# Until today restore.sh checked no identity at all: backups.log has carried
# db=<host>/<name>#<system_identifier> since Pre-deploy 1 (2026-10-17), but
# only the migrate guard read it, so a staging dump could be restored onto
# live with nothing in the way. A database is identified by its cluster's
# system_identifier (pg_control_system, fixed at initdb); a MinIO deployment
# by its deploymentID (.minio.sys/format.json, fixed when the data directory
# is initialised). Both are read live from the environment the operator
# names and compared with what the backup recorded.
#
# Callers set REPO_DIR and source this file. Nothing here prints a secret.

CPS_OPS_LOG="${CPS_OPS_LOG:-$REPO_DIR/docs/ops/backups.log}"
# The MinIO root credentials stay inside the minio container.
CPS_MC_ENV='export MC_HOST_m="http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@localhost:9000"'

cps_env_file() {
  case "$1" in
    live|dev) echo "$REPO_DIR/.env" ;;
    staging) echo "$REPO_DIR/.env.staging" ;;
    *) echo "ERROR: unknown environment \"$1\" (expected live, staging or dev)" >&2; return 1 ;;
  esac
}

cps_env_compose() {
  case "$1" in
    live) echo "docker compose --env-file $REPO_DIR/.env" ;;
    dev) echo "docker compose -p cps-dev --env-file $REPO_DIR/.env -f docker-compose.yml -f docker-compose.dev.yml" ;;
    staging) echo "docker compose -p cps-staging --env-file $REPO_DIR/.env.staging -f docker-compose.yml -f docker-compose.staging.yml" ;;
    *) echo "ERROR: unknown environment \"$1\"" >&2; return 1 ;;
  esac
}

# Runs "$@" inside environment $1's compose project with its env file loaded,
# from infra/ (the compose files are relative). A subshell: nothing leaks.
cps_in_env() {
  local env="$1" envfile compose
  shift
  envfile="$(cps_env_file "$env")" || return 1
  compose="$(cps_env_compose "$env")" || return 1
  (
    set -a
    # shellcheck disable=SC1090
    . "$REPO_DIR/.env"
    [ "$envfile" = "$REPO_DIR/.env" ] || . "$envfile"
    set +a
    cd "$REPO_DIR/infra" && "$@" "$compose"
  )
}

_cps_db_identity_cmd() {
  local compose="$1" id
  id="$($compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc \
    "SELECT system_identifier FROM pg_control_system()" </dev/null 2>/dev/null | tr -d '\r')"
  case "$id" in ''|*[!0-9]*) return 1 ;; esac
  echo "postgres/$POSTGRES_DB#$id"
}

_cps_minio_identity_cmd() {
  local compose="$1" id
  # shellcheck disable=SC2016
  id="$($compose exec -T minio sh -c "$CPS_MC_ENV; mc admin info --json m" </dev/null 2>/dev/null \
    | python3 -c 'import json, sys; print(json.load(sys.stdin)["info"]["deploymentID"])' 2>/dev/null)"
  case "$id" in [0-9a-f]*-*-*-*-*) ;; *) return 1 ;; esac
  echo "minio/$MINIO_BUCKET#$id"
}

# The named environment's identities, read now from the running services.
cps_env_db_identity() { cps_in_env "$1" _cps_db_identity_cmd; }
cps_env_minio_identity() { cps_in_env "$1" _cps_minio_identity_cmd; }

# The db= identity backups.log recorded for this dump file (matched by
# file name; the newest line wins). Empty if the dump has no db= line —
# every dump from before 2026-10-17, and any file backup.sh did not write.
cps_recorded_db_identity() {
  local name
  name="$(basename "$1")"
  [ -f "$CPS_OPS_LOG" ] || return 0
  awk -F'\t' -v name="$name" '
    { n = split($3, parts, "/"); if (parts[n] != name) next
      for (i = 4; i <= NF; i++) if ($i ~ /^db=/) found = substr($i, 4) }
    END { if (found != "") print found }' "$CPS_OPS_LOG"
}

# Refuses (exit 1, by name) unless the dump was recorded as taken from the
# database environment $2 is running right now.
cps_require_dump_from() {
  local dump="$1" env="$2" recorded expected
  recorded="$(cps_recorded_db_identity "$dump")"
  expected="$(cps_env_db_identity "$env")" || {
    echo "REFUSED: could not read the $env database's identity — nothing to compare $(basename "$dump") against." >&2
    return 1
  }
  if [ -z "$recorded" ]; then
    echo "REFUSED: $(basename "$dump") has no recorded source (no db= field for it in $CPS_OPS_LOG) — its origin cannot be checked against $env ($expected)." >&2
    return 1
  fi
  if [ "$recorded" != "$expected" ]; then
    echo "REFUSED: $(basename "$dump") was taken from $recorded, not from $env ($expected)." >&2
    return 1
  fi
  echo "[$(date -Iseconds)] Source check: $(basename "$dump") was taken from $env ($expected)."
}

# A manifest header field (#minio, #pairs, ...), decrypted on the fly.
cps_manifest_field() {
  gpg --batch --quiet --passphrase-file <(printf '%s' "$CPS_BACKUP_ENCRYPTION_PASSPHRASE") --decrypt "$1" 2>/dev/null \
    | awk -F'\t' -v f="#$2" '$1 == f { print $2; exit }'
}

# Refuses (exit 1, by name) unless the manifest was written from environment
# $2's MinIO and belongs with dump $3.
cps_require_manifest_from() {
  local manifest="$1" env="$2" dump="$3" recorded expected pairs
  recorded="$(cps_manifest_field "$manifest" minio)"
  pairs="$(cps_manifest_field "$manifest" pairs)"
  expected="$(cps_env_minio_identity "$env")" || {
    echo "REFUSED: could not read the $env MinIO's identity — nothing to compare $(basename "$manifest") against." >&2
    return 1
  }
  if [ -z "$recorded" ]; then
    echo "REFUSED: $(basename "$manifest") is not a readable attachments manifest (wrong passphrase, or not a manifest)." >&2
    return 1
  fi
  if [ "$recorded" != "$expected" ]; then
    echo "REFUSED: $(basename "$manifest") was taken from $recorded, not from $env ($expected)." >&2
    return 1
  fi
  if [ "$pairs" != "$(basename "$dump")" ]; then
    echo "REFUSED: $(basename "$manifest") belongs with $pairs, not with $(basename "$dump")." >&2
    return 1
  fi
  echo "[$(date -Iseconds)] Source check: $(basename "$manifest") was taken from $env ($expected) with $pairs."
}

# Restores every object a manifest lists as stored ("new" or "kept") from
# the store into the MinIO running in docker container $3, bucket $4 — after
# checking each decrypted object against the manifest's sha256. Prints
# "restored=<n> skipped=<n> bad=<n>"; exit 1 if any stored object is
# missing from the store or does not match.
cps_restore_attachments() {
  local manifest="$1" store="$2" container="$3" bucket="$4" restored=0 skipped=0 bad=0
  local plain
  plain="$(mktemp)"
  gpg --batch --quiet --passphrase-file <(printf '%s' "$CPS_BACKUP_ENCRYPTION_PASSPHRASE") --decrypt "$manifest" > "$plain" 2>/dev/null \
    || { rm -f "$plain"; echo "ERROR: cannot decrypt $manifest" >&2; return 1; }
  while IFS="$(printf '\t')" read -r key sha size status state; do
    case "$key" in '#'*|'') continue ;; esac
    case "$state" in new|kept) ;; *) skipped=$((skipped + 1)); echo "  not in the backup (state $state): $key" >&2; continue ;; esac
    local obj="$store/objects/$key.gpg"
    if [ ! -f "$obj" ]; then
      bad=$((bad + 1)); echo "  MISSING from the store: $key" >&2; continue
    fi
    if [ "$(gpg --batch --quiet --passphrase-file <(printf '%s' "$CPS_BACKUP_ENCRYPTION_PASSPHRASE") --decrypt "$obj" 2>/dev/null | sha256sum | cut -d' ' -f1)" != "$sha" ]; then
      bad=$((bad + 1)); echo "  sha256 MISMATCH in the store: $key" >&2; continue
    fi
    # shellcheck disable=SC2016
    if gpg --batch --quiet --passphrase-file <(printf '%s' "$CPS_BACKUP_ENCRYPTION_PASSPHRASE") --decrypt "$obj" 2>/dev/null \
         | docker exec -i -e K="$key" -e B="$bucket" "$container" sh -c "$CPS_MC_ENV; mc pipe --quiet \"m/\$B/\$K\" >/dev/null"; then
      restored=$((restored + 1))
    else
      bad=$((bad + 1)); echo "  could not write to the target: $key" >&2
    fi
  done < "$plain"
  rm -f "$plain"
  echo "restored=$restored skipped=$skipped bad=$bad"
  [ "$bad" -eq 0 ]
}
