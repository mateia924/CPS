#!/usr/bin/env bash
set -uo pipefail

# Sprint 7.0 (CI #56/#61): CI has never had a single successful run —
# 61/61 (#1 through #61) conclusion=failure, verified via GitHub's own
# public API (docs/SYSTEM_ANALYSIS.md §11). What this project has
# actually relied on for eight days is a human running the equivalent
# checks by hand. This script makes that a named target with a logged
# result (docs/ops/ci-local.log) instead of a verbal practice — the
# same sequence .github/workflows/ci.yml's three jobs run, in the same
# order, plus manage.py check/makemigrations --check (this project's
# own standing full-gate, §0 rule 7, which ci.yml itself doesn't run
# but every block's own close-out always has). Uses CI_OVERLAY=1 for
# the e2e phase — the exact same no-MinIO path real CI now uses — so a
# pass here is the same claim a green CI run would make, not a looser
# one.
#
# Usage: scripts/ci_local.sh   (make ci-local)

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

LOG_DIR="docs/ops"
LOG_FILE="$LOG_DIR/ci-local.log"
mkdir -p "$LOG_DIR"

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

run_step "ruff (lint)" bash -c "docker compose --env-file .env -p cps-dev -f infra/docker-compose.yml -f infra/docker-compose.dev.yml exec -T backend ruff check ."
run_step "manage.py check" bash -c "docker compose --env-file .env -p cps-dev -f infra/docker-compose.yml -f infra/docker-compose.dev.yml exec -T backend python manage.py check"
run_step "makemigrations --check" bash -c "docker compose --env-file .env -p cps-dev -f infra/docker-compose.yml -f infra/docker-compose.dev.yml exec -T backend python manage.py makemigrations --check --dry-run"
run_step "pytest (full deterministic suite)" bash -c "docker compose --env-file .env -p cps-dev -f infra/docker-compose.yml -f infra/docker-compose.dev.yml exec -T backend pytest -q --create-db"
run_step "frontend build (npm ci + npm run build — runs all 7 structural checks via prebuild)" bash -c "cd frontend && npm ci --no-audit --no-fund && npm run build"

# e2e: CI_OVERLAY=1 mirrors the real CI pipeline exactly (no MinIO —
# see infra/docker-compose.ci.yml). Always brings the stack back down
# to the NORMAL (non-CI_OVERLAY) dev-up state afterward, pass or fail,
# so a developer's own cps-dev sandbox isn't left on local storage.
run_step "e2e (dev-up CI_OVERLAY=1 + make e2e)" bash -c "make dev-up CI_OVERLAY=1 && for _ in \$(seq 1 60); do STATUS=\$(curl -s -o /dev/null -w '%{http_code}' http://localhost:3002/admin/login/ || true); [ \"\$STATUS\" != 502 ] && [ \"\$STATUS\" != 503 ] && [ \"\$STATUS\" != 000 ] && break; sleep 2; done && make e2e"
make dev-up >/dev/null 2>&1 || true  # restore the normal (non-CI_OVERLAY) dev-up state regardless of the e2e step's own result

{
  echo "[$(date -Iseconds)] ci-local run"
  for r in "${STEP_RESULTS[@]}"; do echo "  $r"; done
  if [ "$OVERALL" -eq 0 ]; then echo "  OVERALL: PASS"; else echo "  OVERALL: FAIL"; fi
} | tee -a "$LOG_FILE"

exit "$OVERALL"
