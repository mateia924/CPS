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
# Steps: record the git hash being deployed -> build the local overlay's
# images from the CURRENT working tree -> the production gates, defined
# ONCE in scripts/production_gates.sh and run identically by the
# staging rehearsal (scripts/staging_refresh.sh): backup (--target live)
# -> migrate (apps.tenants's guard matches that backup's db= identity)
# -> setup_rls -> verify_rls -> add_missing_system_accounts ->
# check_chart_health --fail-on-findings -> start -> ready -> smoke ->
# one line in docs/ops/deploys.log (time, hash, result).

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOYS_LOG="$REPO_DIR/docs/ops/deploys.log"
COMPOSE="docker compose --env-file $REPO_DIR/.env -f docker-compose.yml -f docker-compose.local.yml"

log() { echo "[deploy $(date -Iseconds)] $1"; }

# Sprint 7.0.2 (incident, 2026-10-04): the night this guard didn't
# exist, a deploy ran from a working tree carrying uncommitted 7.0.1
# fixes on top of the committed 7.0.1 commit — the live database ended
# up built from code that no git hash alone could reconstruct, and
# deploys.log's own one-line record (just a hash) silently implied
# otherwise. Refuses outright by default; the one documented escape
# hatch is explicit on both ends (never silent): set ALLOW_DIRTY_DEPLOY=1
# AND DIRTY_DEPLOY_REASON="..." and rerun — both get logged into
# deploys.log's own record of this run, not just printed and forgotten.
# 7.2.9-c: scripts/backup.sh and this script append a line to
# docs/ops/*.log on every run, so the PREVIOUS deploy's own log line
# leaves the tree dirty and blocks the NEXT one — three deploys were
# blocked this way. Those two files are append-only operational logs,
# never code, so a modification to them alone is not a reason to refuse.
# Filtered out here rather than auto-committed by the script: an
# auto-commit would create a commit AFTER the one being deployed, so
# deploys.log would record a SHA that is not what is running.
# Anything else modified, and any untracked file, still blocks.
DIRTY_STATUS="$(git -C "$REPO_DIR" status --porcelain | grep -v -E "^ ?M +docs/ops/[^/]+\\.log$" || true)"
DIRTY_NOTE=""
if [ -n "$DIRTY_STATUS" ]; then
  if [ "${ALLOW_DIRTY_DEPLOY:-}" = "1" ] && [ -n "${DIRTY_DEPLOY_REASON:-}" ]; then
    log "WARNING: deploying from a DIRTY working tree (ALLOW_DIRTY_DEPLOY=1): $DIRTY_DEPLOY_REASON"
    log "changed file(s):"
    echo "$DIRTY_STATUS" | while IFS= read -r line; do log "  $line"; done
    DIRTY_NOTE=" [DIRTY TREE, ALLOWED: $DIRTY_DEPLOY_REASON]"
  else
    echo "ERROR: working tree is not clean — refusing to deploy. Changed file(s):" >&2
    echo "$DIRTY_STATUS" >&2
    echo "If this is deliberate: ALLOW_DIRTY_DEPLOY=1 DIRTY_DEPLOY_REASON=\"...\" scripts/deploy.sh — logged into deploys.log, never silent." >&2
    exit 1
  fi
fi

# So ${HTTP_PORT:-3000} below actually reflects .env instead of always
# falling back to the default (this script's own shell never inherits
# it otherwise — same pattern scripts/backup.sh already uses).
set -a
source "$REPO_DIR/.env"
set +a

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
  printf '%s\t%s\tFAILED\t%s%s\n' "$(date -Iseconds)" "${GIT_HASH:-unknown}" "$1" "$DIRTY_NOTE" >> "$DEPLOYS_LOG"
  exit 1
}

cd "$REPO_DIR"
GIT_HASH="$(git rev-parse HEAD)"
log "deploying commit $GIT_HASH"

# Pre-deploy 1 (rule 32): build is this script's own step; everything
# after it is the shared gate sequence — this script holds no gate list
# of its own (tests/test_production_gates.py).
log "build images"
cd "$REPO_DIR/infra"
$COMPOSE build || fail "build"

# shellcheck source=production_gates.sh
source "$REPO_DIR/scripts/production_gates.sh"
GATE_REPO_DIR="$REPO_DIR"
GATE_COMPOSE="$COMPOSE"
GATE_BACKUP_TARGET="live"
GATE_BACKUP_REASON="deploy.sh $GIT_HASH"
GATE_HTTP_PORT="${HTTP_PORT:-3000}"
cps_run_gates || fail "$CPS_FAILED_GATE"
cd "$REPO_DIR"

mkdir -p "$(dirname "$DEPLOYS_LOG")"
printf '%s\t%s\tOK\t%s%s\n' "$(date -Iseconds)" "$GIT_HASH" "deploy.sh" "$DIRTY_NOTE" >> "$DEPLOYS_LOG"
log "OK — $GIT_HASH is now live on port ${HTTP_PORT:-3000}. Logged to $DEPLOYS_LOG"
