#!/usr/bin/env bash
# 7.2.9-c: one pytest run at a time, enforced rather than remembered.
# Two concurrent runs against the same container once shared a test
# database; the second run's connections were killed mid-flight and the
# whole first run had to be discarded as untrustworthy — a killed
# connection can mask a failure as easily as cause one. A rule that
# depends on someone checking `docker top` first does not hold; this does.
# Usage: scripts/pytest_run.sh <container> [pytest args...]
#        PYTEST_WORKDIR=/workspace/backend scripts/pytest_run.sh ci-local-backend -q
set -u
LOCK=/run/cps-pytest.lock
WORKDIR="${PYTEST_WORKDIR:-/app}"
CONTAINER="${1:?usage: scripts/pytest_run.sh <container> [pytest args...]}"
shift
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "REFUSED: another pytest run already holds $LOCK." >&2
  echo "Wait for it to finish — two concurrent runs share one test database." >&2
  exit 1
fi
exec docker exec -w "$WORKDIR" "$CONTAINER" pytest "$@"
