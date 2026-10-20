#!/usr/bin/env bash
set -euo pipefail

# CI coverage guard (2026-10-20). Two checks:
# 1. every pytest step in ci.yml is read by the Gate step (and runs exactly
#    one group);
# 2. the set of test files the CI pytest steps COLLECT equals the set of
#    test files present under backend/. Fails
# with the name of every file that exists but no step collects, and of
# every file two steps collect (it would run twice and hide in both).
#
# Why: from 2026-10-04 to 2026-10-20 ci.yml listed its files by name; 24
# test files added in that time were never collected and CI stayed green
# (docs/reports/2026-10-20-ci-coverage.md). The groups now come from
# scripts/ci_test_groups.sh, and this check runs in CI before the tests.
#
# Collection runs with the marker filter switched off (-o addopts=""):
# this is about which FILES are reached, not which markers run. A file
# whose every test is skipped at collection, or that defines no test at
# all, has no collected test and is reported too — a test that cannot
# run is not coverage.
#
# Usage: scripts/check_ci_collection.sh   (needs the backend's Python env:
# CI natively, or a container with the repo, as scripts/ci_local.sh)

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/ci_test_groups.sh
source "$ROOT_DIR/scripts/ci_test_groups.sh"

# Part 1: ci.yml's own pytest steps. The Gate step reads each pytest
# step's steps.<id>.outcome by hand — continue-on-error: true lets every
# step look green, so a step the Gate does not name could fail and CI
# would still pass. Every step whose `run` invokes pytest must have an id
# the Gate reads, and must run exactly one group from ci_test_groups.sh
# (each group exactly once), so the steps and the collection check below
# cannot drift apart. Line-based (no YAML library in the backend env):
# a step starts at "- name:" / "- uses:" at the job's step indent.
CI_YML="${CI_YML:-$ROOT_DIR/.github/workflows/ci.yml}" python3 - <<'PY'
import os, re, sys

text = open(os.environ["CI_YML"], encoding="utf-8").read().splitlines()
steps, current = [], None
for line in text:
    if re.match(r"^      - ", line):
        current = {"lines": [line]}
        steps.append(current)
    elif current is not None and (line.startswith("        ") or not line.strip()):
        current["lines"].append(line)
    elif current is not None and not line.startswith("        "):
        current = None
for step in steps:
    body = "\n".join(step["lines"])
    step["name"] = (re.search(r"name:\s*(.+)", body) or [None, "?"])[1].strip()
    step["id"] = (re.search(r"^\s+id:\s*(\S+)", body, re.M) or [None, None])[1]
    step["body"] = body
    run = body.split("run:", 1)[1] if "run:" in body else ""
    # pytest run as a command (followed by its flags), not the word in a
    # message; the guard's own step and the Gate are not test steps.
    step["pytest"] = (
        bool(re.search(r"\bpytest\s+-", run))
        and "check_ci_collection" not in run
        and not step["name"].startswith("Gate")
    )
    step["groups"] = re.findall(r"\$CI_GROUP_[A-Z_]+|ci_group_rest_args", run)

gate = [s for s in steps if s["name"].startswith("Gate")]
errors = []
if len(gate) != 1:
    errors.append(f"expected exactly one step named 'Gate ...' in ci.yml, found {len(gate)}")
gate_body = gate[0]["body"] if gate else ""
pytest_steps = [s for s in steps if s["pytest"]]
for s in pytest_steps:
    if not s["id"]:
        errors.append(f"pytest step without an id (the Gate cannot read it): {s['name']}")
    elif f"steps.{s['id']}.outcome" not in gate_body:
        errors.append(f"pytest step not covered by the Gate (steps.{s['id']}.outcome missing): {s['name']}")
    if len(s["groups"]) != 1:
        errors.append(f"pytest step must run exactly one group from ci_test_groups.sh, runs {s['groups'] or 'none'}: {s['name']}")
used = [g for s in pytest_steps for g in s["groups"]]
for g in ("$CI_GROUP_ACCOUNTING", "$CI_GROUP_ASSETS_TREASURY", "$CI_GROUP_ATTACHMENTS_PERMISSIONS", "ci_group_rest_args"):
    if used.count(g) != 1:
        errors.append(f"group {g} is run by {used.count(g)} pytest steps, expected 1")
print(f"check_ci_collection: {len(pytest_steps)} pytest steps in ci.yml, all read by the Gate" if not errors else "", end="")
if errors:
    print("FAIL: ci.yml pytest steps and the Gate do not match:", file=sys.stderr)
    for e in errors:
        print(f"  {e}", file=sys.stderr)
    sys.exit(1)
print()
PY

# Part 2: what those steps collect, against what exists.
cd "$ROOT_DIR/backend/tests"

# Test files collected by one pytest invocation, as paths relative to
# backend/ (pytest's rootdir), one per line.
collected() {
  local out
  if ! out="$(pytest --collect-only -q -p no:cacheprovider -o addopts="" "$@" 2>&1)"; then
    echo "$out" | tail -n 30 >&2
    echo "check_ci_collection: collection itself failed for: $*" >&2
    exit 1
  fi
  echo "$out" | sed -n 's#^\([^ :]*\.py\)::.*#\1#p' | sort -u
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
# shellcheck disable=SC2086
collected $CI_GROUP_ACCOUNTING > "$TMP/accounting"
# shellcheck disable=SC2086
collected $CI_GROUP_ASSETS_TREASURY > "$TMP/assets-treasury"
# shellcheck disable=SC2086
collected $CI_GROUP_ATTACHMENTS_PERMISSIONS > "$TMP/attachments-permissions"
# shellcheck disable=SC2046
collected $(ci_group_rest_args) > "$TMP/rest"

(cd "$ROOT_DIR/backend" && find . -name 'test_*.py' -not -path '*/node_modules/*' -not -path '*/.venv/*' \
  -not -path '*/site-packages/*' | sed 's#^\./##' | sort -u) > "$TMP/present"
cat "$TMP/accounting" "$TMP/assets-treasury" "$TMP/attachments-permissions" "$TMP/rest" | sort > "$TMP/all"
sort -u "$TMP/all" > "$TMP/collected"

missing="$(comm -23 "$TMP/present" "$TMP/collected")"
twice="$(uniq -d "$TMP/all")"
echo "check_ci_collection: $(wc -l < "$TMP/present") test files present, $(wc -l < "$TMP/collected") collected by the CI steps"
status=0
if [ -n "$missing" ]; then
  echo "FAIL: test file(s) present but collected by no CI step:" >&2
  echo "$missing" | sed 's/^/  /' >&2
  status=1
fi
if [ -n "$twice" ]; then
  echo "FAIL: test file(s) collected by more than one CI step:" >&2
  echo "$twice" | sed 's/^/  /' >&2
  status=1
fi
[ "$status" -ne 0 ] || echo "check_ci_collection: every test file is collected exactly once."
exit "$status"
