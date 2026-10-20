#!/usr/bin/env bash
# 7.2.9-c: one pytest run at a time, enforced rather than remembered.
# Two concurrent runs against the same container once shared a test
# database; the second run's connections were killed mid-flight and the
# whole first run had to be discarded as untrustworthy — a killed
# connection can mask a failure as easily as cause one. A rule that
# depends on someone checking `docker top` first does not hold; this does.
#
# 2026-10-20 (dev/CI parity): the suite no longer runs inside the dev
# server. It used to `docker exec` into cps-dev-backend-1, which mounts only
# backend/, has no git and no gpg, and runs as root — so 59 tests skipped
# locally that GitHub CI runs, and the root uid hid 4 real failures that
# reached main (docs/reports/2026-10-20-ci-parity-and-protection.md §3).
# Now each run is a throwaway container from the `test` image target
# (backend/Dockerfile: dev + git + gnupg), with the WHOLE repo mounted
# read-only at /workspace and running as uid 1001, the runner's uid. The
# container argument is the template whose network and environment it
# copies (the dev server itself is left untouched).
#
# Usage: scripts/pytest_run.sh <template-container> [pytest args...]
#        e.g. scripts/pytest_run.sh cps-dev-backend-1 -q tests/test_x.py
# Legacy: with PYTEST_WORKDIR set (scripts/ci_local.sh, whose own container
# already holds the repo), pytest runs by `docker exec` in that container.
set -u
LOCK=/run/cps-pytest.lock
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE="${1:?usage: scripts/pytest_run.sh <template-container> [pytest args...]}"
shift
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "REFUSED: another pytest run already holds $LOCK." >&2
  echo "Wait for it to finish — two concurrent runs share one test database." >&2
  exit 1
fi

if [ -n "${PYTEST_WORKDIR:-}" ]; then
  exec docker exec -w "$PYTEST_WORKDIR" "$TEMPLATE" pytest "$@"
fi

docker inspect "$TEMPLATE" >/dev/null 2>&1 || { echo "ERROR: template container $TEMPLATE not found." >&2; exit 1; }
# Cached after the first build; rebuilt only when backend/ changed.
docker build -q --target test -t cps-test:latest "$ROOT_DIR/backend" >/dev/null || {
  echo "ERROR: could not build the test image (backend/Dockerfile target test)." >&2
  exit 1
}
NETWORK="$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$TEMPLATE" | cut -d' ' -f1)"
NAME="cps-pytest-$$"
# Our own named container, removed on every exit path: killing a
# `docker run` client could otherwise leave pytest holding test_cps.
trap 'docker rm -f "$NAME" >/dev/null 2>&1 || true' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
docker run --rm --name "$NAME" --user 1001:1001 -e HOME=/tmp --network "$NETWORK" \
  --env-file <(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$TEMPLATE") \
  -v "$ROOT_DIR:/workspace:ro" -w /workspace/backend --entrypoint pytest \
  cps-test:latest -p no:cacheprovider "$@" &
wait $!
