#!/usr/bin/env bash
set -euo pipefail

# Block 8.2.1: run the backend suite locally the way CI runs it — the four
# groups from scripts/ci_test_groups.sh, each its own pytest process from
# backend/tests, `--create-db` on the first — then the CI Gate's not-run
# check (scripts/ci_gate_counts.sh) on those logs. The per-group counts are
# directly comparable with a CI run's "pytest counts <group>" annotations;
# on 2026-10-20 both gave 245/193/111/476 = 1025 passed, 0 skipped,
# 2 deselected at 8ab75ea.
#
# Same container discipline as scripts/pytest_run.sh: the `test` image,
# uid 1001, the repo read-only at /workspace, the one-pytest-at-a-time lock.
#
# Two environments:
#   (default)  the template container's whole environment — what
#              scripts/pytest_run.sh passes (dev services, dev settings,
#              and every dev secret in that container).
#   --ci-env   ONLY the env block of ci.yml's backend job, read from ci.yml
#              (so it cannot drift), with DATABASE_URL / REDIS_URL pointed
#              at the template's own database and Redis — nothing else.
#              CPS_ENVIRONMENT=ci, local attachment storage, scanning off,
#              no dev secret. A test that passes by default and fails here
#              depends on something CI does not have.
#
# Usage: scripts/ci_groups_local.sh [--ci-env] [TEMPLATE]   (default cps-dev-backend-1)
# Logs:  /var/tmp/cps-ci-groups-<pid>/test-<group>.log (kept; path printed)
# Exit:  0 only if every group passed and the Gate check passed.

MODE="dev-env"
if [ "${1:-}" = "--ci-env" ]; then MODE="ci-env"; shift; fi
TEMPLATE="${1:-cps-dev-backend-1}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="/var/tmp/cps-ci-groups-$$"
NAME="cps-ci-groups-$$"

docker inspect "$TEMPLATE" >/dev/null 2>&1 || { echo "ERROR: template container $TEMPLATE not found." >&2; exit 1; }
exec 9>/run/cps-pytest.lock
if ! flock -n 9; then
  echo "REFUSED: another pytest run already holds /run/cps-pytest.lock." >&2
  exit 1
fi
mkdir -p "$LOG_DIR"
chmod 777 "$LOG_DIR"
trap 'docker rm -f "$NAME" >/dev/null 2>&1 || true' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

docker build -q --target test -t cps-test:latest "$ROOT_DIR/backend" >/dev/null
NETWORK="$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$TEMPLATE" | cut -d' ' -f1)"

# The environment file goes through a process substitution: no value is
# ever on a command line or printed (rule 50).
env_file() {
  local template_env
  template_env="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$TEMPLATE")"
  if [ "$MODE" = "dev-env" ]; then
    printf '%s\n' "$template_env"
    return
  fi
  CI_YML="$ROOT_DIR/.github/workflows/ci.yml" python3 -I -c '
import os, re
lines = open(os.environ["CI_YML"], encoding="utf-8").read().splitlines()
start = lines.index("  backend:")
env_at = next(i for i in range(start, len(lines)) if lines[i] == "    env:")
for line in lines[env_at + 1:]:
    if not line.strip() or line.lstrip().startswith("#"):
        continue
    m = re.match(r"^      ([A-Z_][A-Z0-9_]*):\s*(.*)$", line)
    if not m:
        break
    name, value = m.group(1), m.group(2).strip().strip("\"")
    if name not in ("DATABASE_URL", "REDIS_URL"):
        print(f"{name}={value}")
'
  printf '%s\n' "$template_env" | grep -E '^(DATABASE_URL|REDIS_URL)='
}

echo "[ci-groups] mode: $MODE, template: $TEMPLATE, logs: $LOG_DIR"
set +e
docker run --rm --name "$NAME" --user 1001:1001 -e HOME=/tmp --network "$NETWORK" \
  --env-file <(env_file) \
  -v "$ROOT_DIR:/workspace:ro" -v "$LOG_DIR:/logs" -w /workspace --entrypoint bash \
  cps-test:latest -c '
    source scripts/ci_test_groups.sh
    cd backend/tests
    status=0
    pytest -v -ra --tb=short -p no:cacheprovider --create-db $CI_GROUP_ACCOUNTING > /logs/test-accounting.log 2>&1 || status=1
    pytest -v -ra --tb=short -p no:cacheprovider $CI_GROUP_ASSETS_TREASURY > /logs/test-assets-treasury.log 2>&1 || status=1
    pytest -v -ra --tb=short -p no:cacheprovider $CI_GROUP_ATTACHMENTS_PERMISSIONS > /logs/test-attachments-permissions.log 2>&1 || status=1
    pytest -v -ra --tb=short -p no:cacheprovider $(ci_group_rest_args) > /logs/test-rest.log 2>&1 || status=1
    exit $status
  '
groups_status=$?
set -e

for group in accounting assets-treasury attachments-permissions rest; do
  echo "[$group] $(tail -n 1 "$LOG_DIR/test-$group.log")"
  grep -E '^(FAILED|ERROR) ' "$LOG_DIR/test-$group.log" | head -20 || true
done
gate_status=0
"$ROOT_DIR/scripts/ci_gate_counts.sh" "$LOG_DIR" || gate_status=$?
[ "$groups_status" -eq 0 ] || echo "[ci-groups] at least one group FAILED (see above and $LOG_DIR)." >&2
[ "$groups_status" -eq 0 ] && [ "$gate_status" -eq 0 ]
