#!/usr/bin/env bash
set -uo pipefail

# Sprint 7.0 (CI #56/#61/#62): CI has never had a single successful
# run — 61/61 (#1 through #61) conclusion=failure, verified via
# GitHub's own public API (docs/SYSTEM_ANALYSIS.md §11). What this
# project has actually relied on for eight days is a human running
# the equivalent checks by hand. This script makes that a named
# target with a logged result (docs/ops/ci-local.log) instead of a
# verbal practice.
#
# This is a LITERAL clone of .github/workflows/ci.yml's own backend
# job — a bare python:3.12 container (not cps-dev's already-built
# image, which bakes in whatever pip install produced when that image
# was last built, not necessarily what a fresh `pip install -r
# requirements-dev.txt` would produce today) plus fresh postgres:16-
# alpine/redis:7-alpine containers, same as ci.yml's own `services:`
# block — then the frontend build (npm run build, which runs all 7
# structural checks via its own `prebuild` hook) and e2e
# (CI_OVERLAY=1 — see infra/docker-compose.ci.yml).
#
# Single source of truth: DJANGO_SECRET_KEY/PLATFORM_JWT_SIGNING_KEY
# are read from .env.ci (the same file ci.yml's own values must keep
# matching by hand today — a real, acknowledged gap: GitHub Actions'
# `env:`/`services:` blocks are static YAML and cannot load a file at
# all, so ci.yml's own copies of these two can still drift from
# .env.ci without this script catching it; what THIS script can do is
# never itself hold a second hand-written copy). ATTACHMENT_SCAN_
# ENABLED=false / ATTACHMENT_STORAGE_BACKEND=local / DATABASE_URL /
# REDIS_URL stay hardcoded below, deliberately NOT read from .env.ci:
# this job's own topology (native, no ClamAV, no MinIO, a throwaway
# local postgres/redis) is genuinely different from .env.ci's own (the
# e2e job's full docker-compose stack, real ClamAV/MinIO with its own
# ATTACHMENT_SCAN_ENABLED=true) — blindly inheriting .env.ci's value
# for that one var would silently break this job (scanning flips on
# with no clamd to answer it).
#
# Usage: scripts/ci_local.sh   (make ci-local)

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

LOG_FILE="docs/ops/ci-local.log"
mkdir -p docs/ops

STEP_RESULTS=()
OVERALL=0

run_step() {
  local name="$1"; shift
  echo "[ci-local] step: $name"
  if "$@"; then
    STEP_RESULTS+=("OK	$name")
  else
    STEP_RESULTS+=("FAILED	$name")
    OVERALL=1
  fi
}

DJANGO_SECRET_KEY="$(grep '^DJANGO_SECRET_KEY=' .env.ci | cut -d= -f2-)"
PLATFORM_JWT_SIGNING_KEY="$(grep '^PLATFORM_JWT_SIGNING_KEY=' .env.ci | cut -d= -f2-)"
if [ -z "$DJANGO_SECRET_KEY" ] || [ -z "$PLATFORM_JWT_SIGNING_KEY" ]; then
  echo "[ci-local] FAILED: could not read DJANGO_SECRET_KEY/PLATFORM_JWT_SIGNING_KEY from .env.ci" >&2
  exit 1
fi

cleanup() {
  docker rm -f ci-local-backend ci-local-postgres ci-local-redis >/dev/null 2>&1 || true
  make dev-up >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "[ci-local] starting fresh postgres:16-alpine + redis:7-alpine (same images as ci.yml's own services:)"
docker rm -f ci-local-postgres ci-local-redis >/dev/null 2>&1 || true
docker run -d --name ci-local-postgres -p 5432:5432 -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=cps postgres:16-alpine >/dev/null
docker run -d --name ci-local-redis -p 6379:6379 redis:7-alpine >/dev/null
for _ in $(seq 1 30); do
  PG_OK=$(docker exec ci-local-postgres pg_isready -U postgres 2>&1 | grep -c "accepting connections" || true)
  REDIS_OK=$(docker exec ci-local-redis redis-cli ping 2>&1 | grep -c PONG || true)
  [ "$PG_OK" = "1" ] && [ "$REDIS_OK" = "1" ] && break
  sleep 1
done

echo "[ci-local] starting the backend job's own python:3.12 container (persists across steps, like ci.yml's own job)"
docker rm -f ci-local-backend >/dev/null 2>&1 || true
docker run -d --name ci-local-backend --network host \
  -e RUN="" \
  -e CPS_ENVIRONMENT=ci \
  -e DJANGO_SECRET_KEY="$DJANGO_SECRET_KEY" \
  -e PLATFORM_JWT_SIGNING_KEY="$PLATFORM_JWT_SIGNING_KEY" \
  -e DATABASE_URL=postgres://postgres:postgres@localhost:5432/cps \
  -e REDIS_URL=redis://localhost:6379/0 \
  -e ATTACHMENT_STORAGE_BACKEND=local \
  -e ATTACHMENT_SCAN_ENABLED=false \
  -v "$ROOT_DIR:/workspace" -w /workspace \
  python:3.12 sleep infinity >/dev/null

run_step "install system dependencies (libmagic, git)" docker exec ci-local-backend bash -c "apt-get update -qq && apt-get install -y --no-install-recommends libmagic1 make git >/tmp/apt.log 2>&1"
run_step "install dependencies (requirements-dev.txt)" docker exec ci-local-backend bash -c "pip install -q -r backend/requirements-dev.txt"
run_step "ruff (lint) — same gate as \`make lint\`" docker exec -w /workspace/backend ci-local-backend ruff check .
run_step "manage.py check" docker exec -w /workspace/backend ci-local-backend python manage.py check
run_step "makemigrations --check" docker exec -w /workspace/backend ci-local-backend python manage.py makemigrations --check --dry-run
run_step "collect-only (fast import/collection check — seconds, not minutes)" docker exec -w /workspace/backend ci-local-backend pytest --collect-only -q
run_step "pytest (full deterministic suite) — same gate as \`make test\`" docker exec -w /workspace/backend ci-local-backend pytest -q --create-db

docker rm -f ci-local-backend ci-local-postgres ci-local-redis >/dev/null 2>&1 || true

# node:24 matches ci.yml's own actions/setup-node@v6 node-version:
# "24" — the host shell has no npm/node at all (confirmed live: this
# step silently failed with "npm: command not found" on the first,
# host-direct version of this script, before `make e2e`'s own
# container-based checks happened to mask it as an unrelated-looking
# FAIL). Mirrors the backend job's own "never the host, never cps-dev's
# pre-built image" principle.
run_step "frontend build (npm ci + npm run build — runs all 7 structural checks via prebuild)" \
  docker run --rm -v "$ROOT_DIR/frontend:/workspace" -w /workspace \
  -e NEXT_PUBLIC_API_URL=http://localhost:3000/api \
  node:24 bash -c "npm ci --no-audit --no-fund && npm run build"

echo "[ci-local] bringing up the e2e stack (CI_OVERLAY=1 — no MinIO, local attachment storage, same as real CI)"
make dev-up CI_OVERLAY=1
for _ in $(seq 1 60); do
  STATUS="$(curl -s -o /dev/null -w '%{http_code}' http://localhost:3002/admin/login/ || true)"
  if [ "$STATUS" != "502" ] && [ "$STATUS" != "503" ] && [ "$STATUS" != "000" ]; then
    echo "[ci-local] backend is up (status $STATUS)"
    break
  fi
  sleep 2
done
run_step "e2e (make e2e, same CI_OVERLAY=1 stack)" make e2e

{
  echo "[$(date -Iseconds)] ci-local run"
  for r in "${STEP_RESULTS[@]}"; do echo "  $r"; done
  if [ "$OVERALL" -eq 0 ]; then echo "  OVERALL: PASS"; else echo "  OVERALL: FAIL"; fi
} | tee -a "$LOG_FILE"

exit "$OVERALL"
