#!/usr/bin/env bash
set -euo pipefail

# Block 8.2.1: every e2e spec file present must be run by exactly one
# runner. frontend/e2e/10-reset-password-subdomain-from-host.spec.ts sat in
# the tree from 7.2.9 (44253ac) to 8.2.1 and nothing ran it — the e2e twin
# of the 24 backend test files CI never collected
# (scripts/check_ci_collection.sh).
#
# A runner is a script CI reaches that starts Playwright on named specs.
# Today that is scripts/e2e.sh only (ci.yml "make e2e" -> Makefile e2e ->
# scripts/e2e.sh). scripts/e2e_access.sh is a helper e2e.sh calls with the
# spec name, not a runner. A new runner goes in RUNNERS below, and must be
# reached from CI the same way.
#
# A spec counts as referenced by a runner when its file name appears on a
# non-comment line. Fails naming every spec referenced by no runner, or by
# more than one.
#
# Usage: scripts/check_e2e_runners.sh

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNERS="scripts/e2e.sh"
status=0

grep -qE '^\s+make e2e\b' "$ROOT/.github/workflows/ci.yml" \
  || { echo "check_e2e_runners: ci.yml no longer runs 'make e2e'." >&2; status=1; }
grep -qE '^\s+\./scripts/e2e\.sh\b' "$ROOT/Makefile" \
  || { echo "check_e2e_runners: the Makefile's e2e target no longer runs scripts/e2e.sh." >&2; status=1; }

count=0
for spec_path in "$ROOT"/frontend/e2e/*.spec.ts; do
  spec="$(basename "$spec_path")"
  count=$((count + 1))
  runners=""
  for runner in $RUNNERS; do
    # One process, no pipe: `grep -v … | grep -q` under pipefail failed ~11%
    # of runs (grep -q exits at the first match, the upstream grep dies of
    # SIGPIPE, pipefail makes the pipeline false — block 8.2.1 follow-up).
    if awk -v s="$spec" '!/^[[:space:]]*#/ && index($0, s) { found = 1 } END { exit !found }' "$ROOT/$runner"; then
      runners="$runners $runner"
    fi
  done
  n=$(echo "$runners" | wc -w)
  if [ "$n" -eq 0 ]; then
    echo "check_e2e_runners: NOT RUN by any runner: frontend/e2e/$spec" >&2
    status=1
  elif [ "$n" -gt 1 ]; then
    echo "check_e2e_runners: run by more than one runner ($runners ): frontend/e2e/$spec" >&2
    status=1
  fi
done

[ "$status" -ne 0 ] || echo "check_e2e_runners: all $count e2e spec files are run by exactly one runner ($RUNNERS)."
exit "$status"
