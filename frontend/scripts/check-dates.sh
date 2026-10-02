#!/bin/sh
# Sprint 6.6.6 (docs/prompts/sprint-6.6.md): fails if a date/datetime is
# rendered via a raw, browser-locale-dependent call instead of
# lib/date.ts's formatDate()/formatDateTime() — the exact shape of the
# live "9/30/2026" bug in the asset transfer log (`.toLocaleDateString()`
# with no arguments renders in whatever locale the VIEWER's browser
# happens to be set to, not this project's own DD/MM/YYYY-or-ISO rule).
# Heuristic (grep, not an AST), matching this project's other
# structural checks. A genuinely non-display use (a Date object built
# only to compare against another, never rendered) may carry a
# `// date-ok: <why>` comment to opt out explicitly.
set -e

FAIL=0

echo "== check-dates: .toLocaleDateString()/.toLocaleString() with no locale arg =="
MATCHES=$(find src \( -name '*.tsx' -o -name '*.ts' \) -type f \
  ! -path 'src/lib/date.ts' \
  -exec grep -nE '\.toLocaleDateString\(\)|\.toLocaleString\(\)' {} + | grep -v 'date-ok' || true)
if [ -n "$MATCHES" ]; then
  echo "$MATCHES"
  echo "FAIL: raw .toLocaleDateString()/.toLocaleString() found — use formatDate()/formatDateTime() instead"
  FAIL=1
else
  echo "PASS: no raw .toLocaleDateString()/.toLocaleString() found"
fi

echo ""
echo "== check-dates: Date.toString() =="
MATCHES=$(find src \( -name '*.tsx' -o -name '*.ts' \) -type f \
  ! -path 'src/lib/date.ts' \
  -exec grep -nE '\bDate\([^)]*\)\.toString\(\)' {} + | grep -v 'date-ok' || true)
if [ -n "$MATCHES" ]; then
  echo "$MATCHES"
  echo "FAIL: raw Date(...).toString() found — use formatDate()/formatDateTime() instead"
  FAIL=1
else
  echo "PASS: no raw Date(...).toString() found"
fi

if [ "$FAIL" -ne 0 ]; then
  echo ""
  echo "check-dates: FAILED"
  exit 1
fi
echo ""
echo "check-dates: all checks passed"
