#!/usr/bin/env bash
set -euo pipefail

# Rule 49 (docs/SYSTEM_ANALYSIS.md §4): a guard is proven only by seeing
# its test FAIL with the guard disabled. That proof leaves the guard
# disabled in the tree for as long as the tests run — and 2026-10-17
# (Pre-deploy 1) it stayed that way: the restore was a plain line after
# pytest, `cp` resolved to the shell's `cp -i` alias, and it sat on an
# invisible overwrite prompt while the tree kept the backup guard of
# apps.tenants's migrate accepting any database's backup line. So:
#   - the restore lives in `trap ... EXIT` (INT/TERM/HUP exit through it),
#     never in a line after the run;
#   - it is `command cp -f ... </dev/null` — no alias, no prompt (not
#     `install`: it resets the mode, and a script under proof is executable);
#   - it compares the file with the saved copy and fails loudly if not equal;
#   - the tests run in the background and the script `wait`s on them: bash
#     defers a trapped signal until a FOREGROUND command returns, so a TERM
#     during a ten-minute suite would otherwise restore nothing until the
#     suite was over;
#   - the tests run in a container this script creates and names, never via
#     `docker exec` into a running one: killing an exec client leaves pytest
#     running inside (holding test_cps); `docker rm -f` on our own container
#     ends it. `--rm` covers the normal exit, the trap every other;
#   - SIGKILL cannot be trapped: the saved copy lives at a fixed path
#     outside the process, and a run that finds one already there refuses
#     to start — the previous proof never restored, deal with that first.
#
# Usage: scripts/prove_guard.sh FILE OLD NEW CONTAINER TEST_PATH EXPECTED_FAILURE...
#   FILE              repo-relative file holding the guard
#   OLD / NEW         exact text; OLD must occur exactly once in FILE
#   CONTAINER         a running backend container (cps-dev-backend-1) whose
#                     image, environment, network and volumes the one-off test
#                     container copies; or --repo: the same, from
#                     cps-dev-backend-1, plus the whole repo at /workspace —
#                     for tests that read scripts/ (they skip where only
#                     backend/ is mounted); or --e2e: a Playwright spec run by
#                     scripts/e2e_access.sh against the dev stack, whose
#                     `next dev` picks the disabled guard up on the next
#                     request (block 8.0.1, the first frontend guard proofs)
#   TEST_PATH         pytest path (relative to backend/); with --e2e the spec
#                     file name under frontend/e2e/
#   EXPECTED_FAILURE  test name(s) that must appear as FAILED (with --e2e, the
#                     test title as Playwright's list reporter prints it)
# Exit 0 only if pytest failed, every expected name failed, and FILE is
# byte-identical to its saved copy afterwards.

[ $# -ge 6 ] || { sed -n '/^# Usage:/,/^# byte-identical/p' "$0" >&2; exit 2; }
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FILE="$1" OLD="$2" NEW="$3" CONTAINER="$4" TEST_PATH="$5"
shift 5
TARGET="$REPO_DIR/$FILE"
SAVE_DIR="/var/tmp/cps-guard-proof"
SAVED="$SAVE_DIR/$(echo "$FILE" | tr '/' '_').orig"
TEST_CONTAINER="cps-prove-guard-$$"
TEMPLATE="$CONTAINER"
[ "$CONTAINER" != "--repo" ] || TEMPLATE="cps-dev-backend-1"
[ "$CONTAINER" != "--e2e" ] || TEMPLATE="cps-dev-frontend-1"
TESTS_PID=""
OUTPUT_FILE=""

mkdir -p "$SAVE_DIR"
if [ -n "$(ls -A "$SAVE_DIR")" ]; then
  echo "REFUSED: $SAVE_DIR is not empty — a previous proof never restored its guard:" >&2
  ls -la "$SAVE_DIR" >&2
  echo "Compare each saved copy with its file in the tree (git diff), restore, then delete the saved copy." >&2
  exit 1
fi
[ -f "$TARGET" ] || { echo "ERROR: $TARGET not found." >&2; exit 1; }
docker inspect "$TEMPLATE" >/dev/null 2>&1 || { echo "ERROR: container $TEMPLATE not found." >&2; exit 1; }

# The same lock scripts/pytest_run.sh takes: one pytest against test_cps
# at a time. Held on fd 9 for this script's whole life.
exec 9>/run/cps-pytest.lock
if ! flock -n 9; then
  echo "REFUSED: another pytest run already holds /run/cps-pytest.lock." >&2
  exit 1
fi

restore() {
  local rc=$?
  trap - EXIT INT TERM HUP
  [ -z "$TESTS_PID" ] || kill "$TESTS_PID" 2>/dev/null || true
  docker rm -f "$TEST_CONTAINER" >/dev/null 2>&1 || true
  [ -z "$OUTPUT_FILE" ] || command rm -f "$OUTPUT_FILE"
  if command cp -f "$SAVED" "$TARGET" </dev/null && cmp -s "$SAVED" "$TARGET"; then
    command rm -f "$SAVED"
    echo "[prove_guard] restored: $FILE is byte-identical to its saved copy."
  else
    echo "[prove_guard] RESTORE FAILED: $FILE still holds the disabled guard. Saved copy: $SAVED" >&2
    rc=1
  fi
  exit "$rc"
}

command cp -f "$TARGET" "$SAVED" </dev/null
trap restore EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

OLD="$OLD" NEW="$NEW" python3 -I - "$TARGET" <<'EOF'
import os, sys
path, old, new = sys.argv[1], os.environ["OLD"], os.environ["NEW"]
text = open(path, encoding="utf-8").read()
if text.count(old) != 1:
    sys.exit(f"ERROR: OLD occurs {text.count(old)} time(s) in {path}, expected exactly 1.")
open(path, "w", encoding="utf-8").write(text.replace(old, new))
EOF
echo "[prove_guard] guard disabled in $FILE:"
diff -U0 "$SAVED" "$TARGET" | grep -E '^[-+][^-+]' || true

run_tests() {
  if [ "$CONTAINER" = "--e2e" ]; then
    # The spec's Playwright container gets our name, so restore()'s
    # `docker rm -f` ends it like any other test container here.
    E2E_CONTAINER_NAME="$TEST_CONTAINER" "$REPO_DIR/scripts/e2e_access.sh" "$TEST_PATH"
    return
  fi
  local image network workdir="/app"
  local -a repo_mount=()
  image="$(docker inspect -f '{{.Config.Image}}' "$TEMPLATE")"
  network="$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$TEMPLATE" | cut -d' ' -f1)"
  if [ "$CONTAINER" = "--repo" ]; then
    repo_mount=(-v "$REPO_DIR:/workspace:ro")
    workdir="/workspace/backend"
  fi
  # 2026-10-19: --repo tests may also drive git (test_deploy_sh_guards.py
  # clones the repo). The dev image has no git, so they would SKIP — and a
  # skip is never a FAILED, so the proof could not pass, only stall. Git
  # goes into this throwaway container, as scripts/ci_local.sh does.
  local setup=":"
  [ "$CONTAINER" != "--repo" ] || setup="apt-get update -qq >/dev/null && apt-get install -y -qq --no-install-recommends git >/dev/null && git config --global --add safe.directory '*'"
  docker run --rm --name "$TEST_CONTAINER" --network "$network" \
    --env-file <(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$TEMPLATE") \
    --volumes-from "$TEMPLATE" "${repo_mount[@]}" -w "$workdir" \
    --entrypoint bash "$image" -c "$setup && exec pytest -q -p no:cacheprovider \"\$0\"" "$TEST_PATH"
}

OUTPUT_FILE="$(mktemp -t cps-prove-guard.XXXXXX)"
run_tests >"$OUTPUT_FILE" 2>&1 &
TESTS_PID=$!
set +e
wait "$TESTS_PID"
PYTEST_RC=$?
set -e
TESTS_PID=""
OUTPUT="$(cat "$OUTPUT_FILE")"
echo "$OUTPUT" | grep -E '^(FAILED|ERROR)|✘|passed|failed|REFUSED|Error response' || true
# A browser failure's own detail (which locator, expected vs received,
# the spec line) is the proof worth reading; pytest's -q line names it.
[ "$CONTAINER" != "--e2e" ] || echo "$OUTPUT" | grep -E '^ +(Error:|Locator:|Expected|Received|> [0-9]+ \|)' || true

if [ "$PYTEST_RC" -eq 0 ]; then
  echo "[prove_guard] NOT PROVEN: every test passed with the guard disabled." >&2
  exit 1
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
