#!/bin/sh
# Sprint 6.0.1 (permanent rule 3): fails if a raw money value is rendered
# without going through <Money>/formatMoney() — .toFixed(2) or a money-
# shaped field access ({…total}, {…amount_fc}, {…balance_fc}, {…debit*},
# {…credit*}, {…unit_price}, {…max_balance}, {…credit_limit}) on a line
# that doesn't also mention <Money or formatMoney(. formatMoney() is the
# valid escape hatch where JSX can't be used (an <option> label, a
# DataTable `render` returning a plain string). A line that is
# genuinely not a display (a URL query param, an internal accumulator)
# may carry a `// money-ok: <why>` comment to opt out explicitly.
# Heuristic (grep, not an AST), matching this project's other
# structural checks.
#
# Sprint 6.5.6: FormField's `error={fieldErr.amount_fc}` (etc.) is a
# field-error lookup, not a money display, but matches the same
# ".fieldname}" shape as a real one — excluded alongside the
# <Money>/formatMoney( escape hatches.
set -e

FAIL=0

echo "== check-money: .toFixed(2) outside lib/money.ts =="
MATCHES=$(find src \( -name '*.tsx' -o -name '*.ts' \) -type f \
  ! -path 'src/lib/money.ts' \
  -exec grep -n '\.toFixed(2)' {} + | grep -v 'money-ok' || true)
if [ -n "$MATCHES" ]; then
  echo "$MATCHES"
  echo "FAIL: raw .toFixed(2) found — use formatMoney()/<Money> instead"
  FAIL=1
else
  echo "PASS: no raw .toFixed(2) outside lib/money.ts"
fi

echo ""
echo "== check-money: money-shaped field access without <Money>/formatMoney( =="
PATTERN='\.(total|total_fc|subtotal|tax_total|base_total|amount|amount_fc|balance|balance_fc|paid_fc|debit|debit_fc|credit|credit_fc|unit_price|max_balance|credit_limit|allocated_invoice_fc)\}'
MATCHES=$(find src -name '*.tsx' -type f \
  ! -path 'src/components/Money.tsx' \
  -exec grep -nE "$PATTERN" {} + | grep -v '<Money' | grep -v 'formatMoney(' | grep -v 'money-ok' | grep -v 'fieldErr\.' || true)
if [ -n "$MATCHES" ]; then
  echo "$MATCHES"
  echo "FAIL: raw money field rendered without <Money>/formatMoney( on the same line"
  FAIL=1
else
  echo "PASS: every money field access is wrapped in <Money> or formatMoney("
fi

echo ""
echo "== check-money: a non-zero/blank ternary repeating the raw field (e.g. {x.debit_fc !== \"0.00\" ? x.debit_fc : \"\"}) =="
# Sprint 6.6.6 (item 4): the previous check above only catches
# "{...field}" immediately followed by a closing brace — this exact
# "show it raw if non-zero, else blank" ternary (found live in
# TreasuryMovementsCard.tsx) has a comparison in between, so it slips
# through that one unnoticed while still rendering an unformatted
# number.
PATTERN='!== "0\.00" \?'
MATCHES=$(find src -name '*.tsx' -type f \
  ! -path 'src/components/Money.tsx' \
  -exec grep -nE "$PATTERN" {} + | grep -v '<Money' | grep -v 'formatMoney(' | grep -v 'money-ok' | grep -v 'style={' || true)
if [ -n "$MATCHES" ]; then
  echo "$MATCHES"
  echo "FAIL: a non-zero ternary renders its truthy branch without <Money>/formatMoney("
  FAIL=1
else
  echo "PASS: every non-zero/blank ternary's truthy branch goes through <Money>/formatMoney("
fi

if [ "$FAIL" -ne 0 ]; then
  echo ""
  echo "check-money: FAILED"
  exit 1
fi
echo ""
echo "check-money: all checks passed"
