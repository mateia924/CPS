#!/usr/bin/env bash
set -euo pipefail

# Sprint 6.6.0: the ONLY supported way to change what this host's port
# 3000 (compose project "infra", overlay docker-compose.local.yml)
# serves. Before this script existed, a code change reached port 3000
# the moment it was saved (gunicorn --reload + bind-mounted source) —
# the exact hazard behind the "column does not exist" 500 window (a
# request landing between a model edit and its migration) and behind
# 6.5.15's own migrations running with no fresh backup. This script
# makes every one of those steps explicit, in order, and stops at the
# first failure instead of leaving the live stack half-updated.
#
# Usage: scripts/deploy.sh   (no arguments)
#        make deploy         (same thing)
#
# Steps: record the git hash being deployed -> scripts/backup.sh (logs
# to docs/ops/backups.log) -> build the local overlay's images from
# the CURRENT working tree -> apply migrations (apps.tenants's own
# migrate override still refuses a pending migration without a fresh
# backup — this script's own backup step above is what satisfies it)
# -> recreate the containers from the freshly built images -> make
# smoke -> one line in docs/ops/deploys.log (time, hash, result).

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOYS_LOG="$REPO_DIR/docs/ops/deploys.log"
COMPOSE="docker compose --env-file $REPO_DIR/.env -f docker-compose.yml -f docker-compose.local.yml"

# So ${HTTP_PORT:-3000} below actually reflects .env instead of always
# falling back to the default (this script's own shell never inherits
# it otherwise — same pattern scripts/backup.sh already uses).
set -a
source "$REPO_DIR/.env"
set +a

log() { echo "[deploy $(date -Iseconds)] $1"; }

fail() {
  log "FAILED: $1"
  mkdir -p "$(dirname "$DEPLOYS_LOG")"
  printf '%s\t%s\tFAILED\t%s\n' "$(date -Iseconds)" "${GIT_HASH:-unknown}" "$1" >> "$DEPLOYS_LOG"
  exit 1
}

cd "$REPO_DIR"
GIT_HASH="$(git rev-parse HEAD)"
log "deploying commit $GIT_HASH"

log "step 1/5: backup"
./scripts/backup.sh "deploy.sh $GIT_HASH" || fail "backup.sh"

cd "$REPO_DIR/infra"

log "step 2/5: build images"
$COMPOSE build || fail "build"

log "step 3/5: migrate (apps.tenants's own guard enforces the fresh-backup rule)"
$COMPOSE run --rm --entrypoint '' backend python manage.py migrate || fail "migrate"

log "step 4/5: restart from the freshly built images"
$COMPOSE up -d || fail "restart"

# Sprint 6.6.0 (found while validating this exact script): nginx starts
# and accepts connections well before gunicorn finishes migrate/
# collectstatic/ensure_attachments_bucket and actually binds — a smoke
# check that races this window gets one spurious 502, not a real
# failure. Poll (not sleep-once) until the backend answers or this
# many tries are exhausted, then hand off to smoke.sh for the real check.
log "waiting for the backend to actually accept connections"
READY=0
for _ in $(seq 1 30); do
  STATUS="$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:${HTTP_PORT:-3000}/api/auth/login/" -X POST \
    -H "Content-Type: application/json" -d '{}' || true)"
  # nginx itself always answers (curl's own exit code alone can't tell
  # "backend is up" from "backend refused the connection" — nginx
  # returns a real 502/503 to the client either way) — a 400 here means
  # the request actually reached Django and got validated/rejected,
  # proof the backend is genuinely serving.
  if [ "$STATUS" != "502" ] && [ "$STATUS" != "503" ] && [ "$STATUS" != "000" ]; then
    READY=1
    break
  fi
  sleep 1
done
[ "$READY" = "1" ] || fail "backend never accepted a connection within 30s (last status: ${STATUS:-none})"

log "step 5/5: smoke test"
cd "$REPO_DIR"
./scripts/smoke.sh || fail "smoke"

mkdir -p "$(dirname "$DEPLOYS_LOG")"
printf '%s\t%s\tOK\t%s\n' "$(date -Iseconds)" "$GIT_HASH" "deploy.sh" >> "$DEPLOYS_LOG"
log "OK — $GIT_HASH is now live on port ${HTTP_PORT:-3000}. Logged to $DEPLOYS_LOG"
