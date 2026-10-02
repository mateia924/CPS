#!/bin/sh
# Sprint 6.6.6 (docs/prompts/sprint-6.6.md): fails if a document number
# (invoice/voucher/journal entry "number"/"entry_number") is rendered
# as plain text instead of a <Link> to that document's own detail
# page — the live gaps this closes: the ledger report's own entry
# number, and the customer/employee detail screens' invoice/voucher
# history tabs. Heuristic (grep, not an AST), matching this project's
# other structural checks. `src/app/print/**` is excluded on purpose —
# a printed/PDF document has no clickable links. A line that is
# genuinely not a navigable reference (a form field name, a numeric
# input) may carry a `// links-ok: <why>` comment either on the SAME
# line or on the line directly ABOVE it (the only legal spot for a
# plain `//` comment right before a lone JSX element returned as the
# sole expression of an arrow function, e.g. inside `.map(x => (...))`
# — a trailing `{/* ... */}` sibling there is a syntax error, not just
# a style nit: found live, the hard way, while writing this script).
set -e

FAIL=0

echo "== check-links: a document number rendered without a <Link> on the same line =="
PATTERN='[.](number|entry_number)[}]'
MATCHES=$(find src -name '*.tsx' -type f ! -path 'src/app/print/*' -print0 \
  | xargs -0 awk -v pattern="$PATTERN" '
    FNR > 1 && $0 ~ pattern {
      window = prev "\n" $0
      if (window !~ /links-ok/ && window !~ /fieldErr\./ && window !~ /FormField / && window !~ /<Link/) {
        print FILENAME ":" FNR ": " $0
      }
    }
    { prev = $0 }
  ')
if [ -n "$MATCHES" ]; then
  echo "$MATCHES"
  echo "FAIL: a document number is rendered without a <Link> to its own detail page on the same or preceding line"
  FAIL=1
else
  echo "PASS: every document number renders through a <Link>"
fi

if [ "$FAIL" -ne 0 ]; then
  echo ""
  echo "check-links: FAILED"
  exit 1
fi
echo ""
echo "check-links: all checks passed"
