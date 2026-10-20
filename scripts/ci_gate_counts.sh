#!/usr/bin/env bash
set -euo pipefail

# Block 8.2.1: the CI Gate's "tests that did not run" check, moved out of
# ci.yml so a test can drive it (backend/tests/test_ci_gate_counts.py) and
# rule 49 can break it. Reads each step's log (/tmp/test-<group>.log in CI)
# and fails if its skipped or deselected count is above the ceiling in
# scripts/ci_test_groups.sh. A bump there needs a dated reason.
#
# Usage: scripts/ci_gate_counts.sh [LOG_DIR]   (default /tmp)

LOG_DIR="${1:-/tmp}"
# shellcheck source=ci_test_groups.sh
source "$(dirname "${BASH_SOURCE[0]}")/ci_test_groups.sh"

over=""; total_passed=0; total_skipped=0; total_deselected=0
for spec in "accounting:$CI_MAX_SKIPPED_ACCOUNTING:$CI_MAX_DESELECTED_ACCOUNTING" \
            "assets-treasury:$CI_MAX_SKIPPED_ASSETS_TREASURY:$CI_MAX_DESELECTED_ASSETS_TREASURY" \
            "attachments-permissions:$CI_MAX_SKIPPED_ATTACHMENTS_PERMISSIONS:$CI_MAX_DESELECTED_ATTACHMENTS_PERMISSIONS" \
            "rest:$CI_MAX_SKIPPED_REST:$CI_MAX_DESELECTED_REST"; do
  IFS=: read -r group ceiling dceiling <<< "$spec"
  log="$LOG_DIR/test-$group.log"
  if [ ! -f "$log" ]; then
    over="$over $group(no log)"
    continue
  fi
  # pytest's final line: "==== 980 passed, 2 skipped, 2 deselected in 9.1s ===="
  line="$(grep -E '^=+ .*(passed|failed|error).* in [0-9.]+s' "$log" | tail -n 1 || true)"
  p=$(echo "$line" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+' || echo 0)
  k=$(echo "$line" | grep -oE '[0-9]+ skipped' | grep -oE '[0-9]+' || echo 0)
  d=$(echo "$line" | grep -oE '[0-9]+ deselected' | grep -oE '[0-9]+' || echo 0)
  total_passed=$((total_passed + p)); total_skipped=$((total_skipped + k)); total_deselected=$((total_deselected + d))
  echo "$group: $p passed, $k skipped (ceiling $ceiling), $d deselected (ceiling $dceiling)"
  [ "$k" -le "$ceiling" ] || over="$over $group(skipped $k>$ceiling)"
  [ "$d" -le "$dceiling" ] || over="$over $group(deselected $d>$dceiling)"
done
echo "::notice title=pytest total::$total_passed passed, $total_skipped skipped, $total_deselected deselected"
if [ -n "$over" ]; then
  echo "::error::Tests not run above the recorded ceiling:$over — a test stopped running. See the 'pytest skipped' / 'pytest deselected' annotations (at most 60 lines per step), then fix it or raise the ceiling in scripts/ci_test_groups.sh with a dated reason."
  exit 1
fi
