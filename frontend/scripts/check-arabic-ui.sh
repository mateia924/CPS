#!/bin/sh
# Sprint 6.6.6 (docs/prompts/sprint-6.6.md): fails if a raw backend
# enum value (approved/BLOCK/WARN/INFO/unmatched/…) reaches the screen
# instead of going through a key-to-translation-key map + `t()` — the
# live bugs this closes: the opening-balance readiness list showing
# literal "[BLOCK]"/"[WARN]"/"[INFO]", the bank reconciliation tab
# showing literal "unmatched"/"matched"/"ignored", and the numbering
# settings screen showing a literal "journal_entry"/"voucher_receipt".
# Heuristic (grep, not an AST), matching this project's other
# structural checks. A line that renders a `.status`/`.level`/
# `.doc_type`/`.kind` value that is genuinely not UI-facing text (a
# React `key=`, an API path segment, a field name for `fieldErr.`
# lookup) may carry a `// arabic-ok: <why>` comment to opt out
# explicitly.
set -e

FAIL=0

echo "== check-arabic-ui: raw enum rendered in upper case (e.g. [BLOCK]) =="
MATCHES=$(find src \( -name '*.tsx' -o -name '*.ts' \) -type f \
  -exec grep -nE '\.toUpperCase\(\)\}' {} + | grep -v 'arabic-ok' || true)
if [ -n "$MATCHES" ]; then
  echo "$MATCHES"
  echo "FAIL: a raw value is being upper-cased for display — translate it through t() instead"
  FAIL=1
else
  echo "PASS: no raw .toUpperCase()} found"
fi

echo ""
echo "== check-arabic-ui: .status}/.level}/.doc_type} rendered without t( on the same line =="
PATTERN='\.(status|level|doc_type)\}'
MATCHES=$(find src -name '*.tsx' -type f \
  -exec grep -nE "$PATTERN" {} + \
  | grep -v 'arabic-ok' \
  | grep -v 'fieldErr\.' \
  | grep -v 'FormField ' \
  | grep -v 'StatusBadge' \
  | grep -v 't(' \
  || true)
if [ -n "$MATCHES" ]; then
  echo "$MATCHES"
  echo "FAIL: a raw .status/.level/.doc_type value is rendered without t( on the same line"
  FAIL=1
else
  echo "PASS: every .status/.level/.doc_type render goes through t("
fi

if [ "$FAIL" -ne 0 ]; then
  echo ""
  echo "check-arabic-ui: FAILED"
  exit 1
fi
echo ""
echo "check-arabic-ui: all checks passed"
