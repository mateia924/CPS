#!/usr/bin/env bash
set -euo pipefail

# Rule 49 (docs/SYSTEM_ANALYSIS.md §4): a guard is proven only by seeing
# its test FAIL with the guard disabled.
#
# 2026-10-20: the guard is disabled in a COPY of the working tree, never in
# /opt/cps itself. Until today this script edited the real file in /opt/cps
# and restored it from /var/tmp in an EXIT trap. But /opt/cps is the live
# server's working tree (cron runs scripts/backup.sh from it every night,
# deploy.sh builds from it), and the dev stack mounts its backend/ and
# frontend/ live — so for the length of every proof a guard really was off
# in the tree, served by the dev server, and a SIGKILL (no trap) would have
# left it off. 2026-10-17 had already shown the restore can fail (a `cp -i`
# alias sat on a hidden prompt for 30 minutes). Now:
#   - each run copies the working tree (uncommitted changes included —
#     guards are proven before their commit) to /var/tmp/cps-proof-<pid>/,
#     without node_modules, .next, test output, and without .env (secrets
#     are not copied around);
#   - the guard is disabled in the copy only; /opt/cps is never written. The
#     real FILE's sha256 is taken before and after the run, and the run fails
#     if it changed;
#   - pytest runs in a container this script names, from the `test` image
#     (git, gnupg), with the COPY read-only at /workspace, as uid 1001 —
#     the same container scripts/pytest_run.sh uses;
#   - --e2e (frontend files only): a throwaway `next dev` serves the COPY's
#     frontend/, behind a throwaway nginx on port $PROOF_HTTP_PORT that sends
#     /api to the dev backend (same origin, so no CORS), and the COPY's
#     scripts/e2e_access.sh runs the spec against it. The dev server keeps
#     serving the unmodified /opt/cps;
#   - everything the run created (the copy, its containers) goes in the EXIT
#     trap; a SIGKILL can leave only those behind, never a disabled guard.
#
# Usage: scripts/prove_guard.sh FILE OLD NEW CONTAINER TEST_PATH EXPECTED_FAILURE...
#   FILE              repo-relative file holding the guard
#   OLD / NEW         exact text; OLD must occur exactly once in FILE
#   CONTAINER         a backend container (cps-dev-backend-1) whose network and
#                     environment the test container copies; --repo is the same
#                     (kept for its callers: the repo is always mounted now); or
#                     --e2e: TEST_PATH is a Playwright spec under frontend/e2e/,
#                     run by the copy's scripts/e2e_access.sh against the copy's
#                     frontend. FILE must be under frontend/ (the dev backend
#                     serves /opt/cps, so a backend change would not be seen).
#   TEST_PATH         pytest path (relative to backend/); with --e2e the spec name
#   EXPECTED_FAILURE  test name(s) that must appear as FAILED (with --e2e, the
#                     test title as Playwright's list reporter prints it)
# Exit 0 only if the tests failed, every expected name failed, and FILE in
# /opt/cps is byte-identical before and after.

[ $# -ge 6 ] || { sed -n '/^# Usage:/,/^# \/opt\/cps is byte-identical/p' "$0" >&2; exit 2; }
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FILE="$1" OLD="$2" NEW="$3" CONTAINER="$4" TEST_PATH="$5"
shift 5
TARGET="$REPO_DIR/$FILE"
TEMPLATE="$CONTAINER"
{ [ "$CONTAINER" != "--repo" ] && [ "$CONTAINER" != "--e2e" ]; } || TEMPLATE="cps-dev-backend-1"
PROOF_DIR="/var/tmp/cps-proof-$$"
COPY="$PROOF_DIR/repo"
TEST_CONTAINER="cps-prove-guard-$$"
FE_CONTAINER="cps-proof-fe-$$"
PROXY_CONTAINER="cps-proof-proxy-$$"
PROOF_HTTP_PORT="${PROOF_HTTP_PORT:-3012}"
TESTS_PID=""

[ -f "$TARGET" ] || { echo "ERROR: $TARGET not found." >&2; exit 1; }
docker inspect "$TEMPLATE" >/dev/null 2>&1 || { echo "ERROR: container $TEMPLATE not found." >&2; exit 1; }
if [ "$CONTAINER" = "--e2e" ] && [[ "$FILE" != frontend/* ]]; then
  echo "REFUSED: --e2e proves frontend/ files only — the dev backend serves /opt/cps, not the copy." >&2
  exit 2
fi
for leftover in /var/tmp/cps-proof-*; do
  [ -e "$leftover" ] || continue
  pid="${leftover##*-}"
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "[prove_guard] removing a leftover copy from a killed run: $leftover" >&2
    command rm -rf "$leftover"
  fi
done

# The same lock scripts/pytest_run.sh takes: one pytest against test_cps
# at a time. Held on fd 9 for this script's whole life.
exec 9>/run/cps-pytest.lock
if ! flock -n 9; then
  echo "REFUSED: another pytest run already holds /run/cps-pytest.lock." >&2
  exit 1
fi

BEFORE_SHA="$(sha256sum "$TARGET" | cut -d' ' -f1)"

cleanup() {
  local rc=$?
  trap - EXIT INT TERM HUP
  [ -z "$TESTS_PID" ] || kill "$TESTS_PID" 2>/dev/null || true
  docker rm -f "$TEST_CONTAINER" "$FE_CONTAINER" "$PROXY_CONTAINER" >/dev/null 2>&1 || true
  docker rm -f "cps-e2e-access-$$" >/dev/null 2>&1 || true
  command rm -rf "$PROOF_DIR"
  local after
  after="$(sha256sum "$TARGET" | cut -d' ' -f1)"
  if [ "$after" = "$BEFORE_SHA" ]; then
    echo "[prove_guard] /opt/cps untouched: $FILE has the same sha256 before and after ($BEFORE_SHA)."
  else
    echo "[prove_guard] ERROR: $FILE in /opt/cps CHANGED during the run ($BEFORE_SHA -> $after)." >&2
    rc=1
  fi
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

mkdir -p "$PROOF_DIR"
# The working tree as it is now (tracked and untracked files, uncommitted
# edits included), minus what is regenerated or secret.
rsync -a --delete \
  --exclude=node_modules --exclude=.next --exclude=test-results --exclude=__pycache__ \
  --exclude=/.env --exclude='/.env.*' --exclude=/infra/fail2ban \
  "$REPO_DIR/" "$COPY/"

OLD="$OLD" NEW="$NEW" python3 -I - "$COPY/$FILE" <<'EOF'
import os, sys
path, old, new = sys.argv[1], os.environ["OLD"], os.environ["NEW"]
text = open(path, encoding="utf-8").read()
if text.count(old) != 1:
    sys.exit(f"ERROR: OLD occurs {text.count(old)} time(s) in {path}, expected exactly 1.")
open(path, "w", encoding="utf-8").write(text.replace(old, new))
EOF
echo "[prove_guard] guard disabled in the COPY ($COPY/$FILE), not in /opt/cps:"
diff -U0 "$TARGET" "$COPY/$FILE" | grep -E '^[-+][^-+]' || true

start_frontend_from_copy() {
  local network fe_image api_origin
  network="$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' cps-dev-frontend-1 | cut -d' ' -f1)"
  fe_image="$(docker inspect -f '{{.Config.Image}}' cps-dev-frontend-1)"
  api_origin="$(grep '^DEV_NEXT_PUBLIC_API_URL=' "$REPO_DIR/.env" | cut -d= -f2- | sed -E 's#^(https?://[^:/]+).*#\1#'):$PROOF_HTTP_PORT"
  docker run -d --name "$FE_CONTAINER" --network "$network" \
    -e NEXT_PUBLIC_API_URL="$api_origin/api" -e NEXT_PUBLIC_APP_DOMAIN="${api_origin#*://}" \
    -v "$COPY/frontend:/app" -v cps-dev_frontend_node_modules:/app/node_modules:ro \
    -w /app --entrypoint sh "$fe_image" -c "exec npx next dev -p 3000" >/dev/null
  sed -e "s/server frontend:3000;/server $FE_CONTAINER:3000;/" "$REPO_DIR/infra/nginx/nginx.conf" > "$PROOF_DIR/nginx.conf"
  docker run -d --name "$PROXY_CONTAINER" --network "$network" -p "$PROOF_HTTP_PORT:80" \
    -v "$PROOF_DIR/nginx.conf:/etc/nginx/conf.d/default.conf:ro" nginx:1.27-alpine >/dev/null
  for _ in $(seq 1 90); do
    [ "$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$PROOF_HTTP_PORT/login")" = "200" ] && { echo "$api_origin"; return 0; }
    sleep 2
  done
  echo "ERROR: the copy's frontend never answered on port $PROOF_HTTP_PORT." >&2
  docker logs --tail 30 "$FE_CONTAINER" >&2 || true
  return 1
}

run_tests() {
  if [ "$CONTAINER" = "--e2e" ]; then
    local origin
    origin="$(start_frontend_from_copy)"
    E2E_API_URL="$origin/api" E2E_ENV_FILE="$REPO_DIR/.env" E2E_CONTAINER_NAME="cps-e2e-access-$$" \
      E2E_NODE_MODULES="$REPO_DIR/frontend/node_modules" \
      "$COPY/scripts/e2e_access.sh" "$TEST_PATH"
    return
  fi
  local network
  docker build -q --target test -t cps-test:latest "$COPY/backend" >/dev/null
  network="$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$TEMPLATE" | cut -d' ' -f1)"
  docker run --rm --name "$TEST_CONTAINER" --user 1001:1001 -e HOME=/tmp --network "$network" \
    --env-file <(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$TEMPLATE") \
    -v "$COPY:/workspace:ro" -w /workspace/backend --entrypoint pytest \
    cps-test:latest -q -p no:cacheprovider "$TEST_PATH"
}

OUTPUT_FILE="$PROOF_DIR/output.txt"
run_tests >"$OUTPUT_FILE" 2>&1 &
TESTS_PID=$!
set +e
wait "$TESTS_PID"
TESTS_RC=$?
set -e
TESTS_PID=""
OUTPUT="$(cat "$OUTPUT_FILE")"
echo "$OUTPUT" | grep -E '^(FAILED|ERROR)|✘|passed|failed|REFUSED|Error response|never answered' || true
# A failure's own detail is the proof worth reading: a browser failure's
# locator, expected vs received and spec line; pytest's assertion lines.
if [ "$CONTAINER" = "--e2e" ]; then
  echo "$OUTPUT" | grep -E '^ +(Error:|Locator:|Expected|Received|> ?[0-9]+ \||at .*\.spec\.ts:[0-9]+)' || true
else
  echo "$OUTPUT" | grep -E '^E   ' | head -12 || true
fi

if [ "$TESTS_RC" -eq 0 ]; then
  echo "[prove_guard] NOT PROVEN: every test passed with the guard disabled." >&2
  exit 1
fi
if ! echo "$OUTPUT" | grep -qE '^FAILED |✘'; then
  # Nothing failed BY NAME: the run broke before or around the tests.
  echo "[prove_guard] the test run failed without a named test failure — its last lines:" >&2
  echo "$OUTPUT" | tail -n 25 >&2
fi
missing=0
for name in "$@"; do
  if [ "$CONTAINER" = "--e2e" ]; then
    pattern="✘ .* › ${name}( \(|$)"
  else
    pattern="^FAILED .*::${name}( |\[|$)"
  fi
  if ! echo "$OUTPUT" | grep -qE "$pattern"; then
    echo "[prove_guard] NOT PROVEN: $name did not fail." >&2
    missing=1
  fi
done
[ "$missing" -eq 0 ] || exit 1
echo "[prove_guard] PROVEN: $* failed with the guard disabled."
