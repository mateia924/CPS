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

# Incident, 2026-10-01 (docs/SYSTEM_ANALYSIS.md §11): the real .env got
# mistakenly overwritten with .env.example's own placeholder values
# during CI-reproduction testing and not fully reverted — nothing broke
# immediately (already-running containers keep their own baked-in
# environment), but the NEXT deploy would have rebuilt against
# "change-me" secrets and silently broken auth against the real,
# already-initialized Postgres/MinIO. §0 rule 9 (docs/prompts/
# sprint-6.6.md): the live .env is never touched for any experiment or
# reproduction — environment simulation happens in an isolated git
# worktree (/opt/cps-ci) with its own env file instead. This check is
# the structural backstop for that rule: refuse outright if any
# required secret still holds the literal "change-me..." placeholder
# every single one of them uses in .env.example.
# Sprint 6.6.5 (CI #46): the ONLY exception — .env.ci (the e2e job's
# own committed, non-secret test env file, never this script's real
# $REPO_DIR/.env in normal operation) legitimately isn't real secrets
# either, and is explicitly allowed to say so via this one flag rather
# than needing "change-me"-shaped values of its own. Everything else
# about this guard (which file, which vars) is unchanged.
# Sprint 6.6.5 fix (found live, the hard way — the first deploy.sh run
# after introducing this exact line died here, silently, with no error
# message at all): `grep -m1` exits 1 on no match, and this whole
# script runs under `set -e` — the real .env has no CPS_ENVIRONMENT
# line at all (that var is only ever set directly in docker-compose.
# prod.yml/staging.yml's own `environment:` blocks, never via .env),
# so this killed the script before it printed a single line, before
# even the backup step. `|| true` here and on the loop's own grep
# below (same failure mode for any required var genuinely missing)
# makes "no match" a normal, handled case instead of a silent death.
CPS_ENVIRONMENT_VALUE="$(grep -m1 "^CPS_ENVIRONMENT=" "$REPO_DIR/.env" | cut -d= -f2- || true)"
if [ "$CPS_ENVIRONMENT_VALUE" = "ci" ]; then
  log "CPS_ENVIRONMENT=ci — skipping the placeholder-secret guard (see .env.ci)"
else
REQUIRED_SECRET_VARS="DJANGO_SECRET_KEY PLATFORM_JWT_SIGNING_KEY POSTGRES_PASSWORD POSTGRES_APP_PASSWORD MINIO_ACCESS_KEY MINIO_SECRET_KEY ATTACHMENT_LINK_SIGNING_KEY CPS_BACKUP_ENCRYPTION_PASSPHRASE"
for VAR in $REQUIRED_SECRET_VARS; do
  VALUE="$(grep -m1 "^${VAR}=" "$REPO_DIR/.env" | cut -d= -f2- || true)"
  case "$VALUE" in
    change-me*)
      echo "ERROR: .env still holds .env.example's own placeholder for $VAR (\"$VALUE\") — refusing to deploy. Never copy .env.example over the real .env; use an isolated git worktree (/opt/cps-ci, its own env file) for any environment simulation instead. See docs/SYSTEM_ANALYSIS.md §11 (2026-10-01 incident) and docs/ops/DEPLOY.md." >&2
      exit 1
      ;;
  esac
done
fi

# Sprint 7.0 (CI #56 follow-up, decision 8): the same production rule
# config/settings.py already enforces at Django boot
# (ATTACHMENT_SCAN_ENABLED=false raises ImproperlyConfigured when
# CPS_ENVIRONMENT=production) — checked again here, one layer earlier,
# on the host, before even building an image: this deploy script
# itself has no business targeting a production .env in the first
# place (that's docker-compose.prod.yml's own concern, 6.6.8), but if
# CPS_ENVIRONMENT ever legitimately is "production" in .env, scanning
# disabled must refuse here too, not only inside the container.
if [ "$CPS_ENVIRONMENT_VALUE" = "production" ]; then
  ATTACHMENT_SCAN_VALUE="$(grep -m1 "^ATTACHMENT_SCAN_ENABLED=" "$REPO_DIR/.env" | cut -d= -f2- || true)"
  case "$ATTACHMENT_SCAN_VALUE" in
    false|False|FALSE|0)
      echo "ERROR: CPS_ENVIRONMENT=production but ATTACHMENT_SCAN_ENABLED=$ATTACHMENT_SCAN_VALUE in .env — refusing to deploy. Every uploaded file must be virus-scanned before it's served in production (same rule config/settings.py enforces at Django boot)." >&2
      exit 1
      ;;
  esac
fi

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
# Polls /admin/login/ (Django, always present, never rate-limited) —
# NOT /api/auth/login/: a first cut of this polled that endpoint
# directly and burned through nginx's own login rate limit (auth_login
# zone, burst=5) before smoke.sh ever got to make its own real login
# call, failing smoke with a spurious 429 instead of ever finishing.
log "waiting for the backend to actually accept connections"
READY=0
for _ in $(seq 1 30); do
  STATUS="$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:${HTTP_PORT:-3000}/admin/login/" || true)"
  # nginx itself always answers (curl's own exit code alone can't tell
  # "backend is up" from "backend refused the connection" — nginx
  # returns a real 502/503 to the client either way) — any real HTTP
  # status here (200 for the login page) means the request actually
  # reached Django, proof the backend is genuinely serving.
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
