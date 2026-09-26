#!/bin/sh
# Sprint 6.5.6 (docs/SYSTEM_ANALYSIS.md §3.18 standing rule, first human
# UAT fix): fails if a raw <input>/<select>/<textarea> is rendered
# outside the shared FormField component, or if a raw backend field
# name leaks to the user (the exact "Object.entries(fieldErr).map(...)"
# dump this same UAT round found and removed from the voucher forms —
# FormField's own per-field error display is the only sanctioned way
# to show a field-level API error). A field that is genuinely not a
# validated data-entry field (a DataTable search box, a checkbox, a
# GET-only report filter with no field-level API errors ever returned)
# may carry a `// form-ok: <why>` comment to opt out explicitly — same
# escape-hatch convention as check-money.sh's `money-ok`. Heuristic
# (grep, not an AST), matching this project's other structural checks.
set -e

FAIL=0

echo "== check-forms: raw input/select/textarea outside FormField.tsx =="
# A wrapped field's raw <input>/<select>/<textarea> tag is still
# physically present in the file as FormField's JSX child, so a plain
# grep can't tell "wrapped" from "not wrapped" — it would flag every
# compliant field too. Track <FormField>...</FormField> nesting depth
# per line instead (this codebase always opens/closes FormField on its
# own line) and only flag the element when depth is 0.
MATCHES=$(find src \( -name '*.tsx' \) -type f ! -path 'src/components/FormField.tsx' -print0 | xargs -0 awk '
  FNR==1 { depth=0 }
  /<FormField/ { depth++ }
  /<(input|select|textarea)[ \/>]/ && depth==0 && !/form-ok/ { print FILENAME":"FNR":"$0 }
  /<\/FormField>/ { depth-- }
')
if [ -n "$MATCHES" ]; then
  echo "$MATCHES"
  echo "FAIL: raw <input>/<select>/<textarea> found outside FormField — wrap it, or add // form-ok: <why>"
  FAIL=1
else
  echo "PASS: every input/select/textarea is wrapped in FormField (or explicitly exempted)"
fi

echo ""
echo "== check-forms: raw field-name error dumps (Object.entries(fieldErr...)) =="
MATCHES=$(find src -name '*.tsx' -type f -exec grep -n 'Object\.entries(fieldErr' {} + || true)
if [ -n "$MATCHES" ]; then
  echo "$MATCHES"
  echo "FAIL: a raw {field: message} dump leaks the technical field name — use FormField's own error prop per field instead"
  FAIL=1
else
  echo "PASS: no raw field-error dump found"
fi

if [ "$FAIL" -ne 0 ]; then
  echo ""
  echo "check-forms: FAILED"
  exit 1
fi
echo ""
echo "check-forms: all checks passed"
