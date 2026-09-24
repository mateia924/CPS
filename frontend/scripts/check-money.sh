#!/bin/sh
# Sprint 6.0.1 (permanent rule 3): fails if a raw money value is rendered
# in JSX without going through <Money>/formatMoney — .toFixed(2) or a
# money-shaped field access ({…total}, {…amount_fc}, {…balance_fc},
# {…debit*}, {…credit*}, {…unit_price}, {…max_balance}, {…credit_limit})
# on a line that doesn't also mention <Money. Heuristic (grep, not an
# AST), matching this project's other structural checks.
set -e

FAIL=0

echo "== check-money: .toFixed(2) outside lib/money.ts =="
MATCHES=$(find src \( -name '*.tsx' -o -name '*.ts' \) -type f \
  ! -path 'src/lib/money.ts' \
  -exec grep -n '\.toFixed(2)' {} + || true)
if [ -n "$MATCHES" ]; then
  echo "$MATCHES"
  echo "FAIL: raw .toFixed(2) found — use formatMoney()/<Money> instead"
  FAIL=1
else
  echo "PASS: no raw .toFixed(2) outside lib/money.ts"
fi

echo ""
echo "== check-money: money-shaped field access without <Money =="
PATTERN='\.(total|total_fc|subtotal|tax_total|base_total|amount|amount_fc|balance|balance_fc|paid_fc|debit|debit_fc|credit|credit_fc|unit_price|max_balance|credit_limit|allocated_invoice_fc)\}'
MATCHES=$(find src -name '*.tsx' -type f \
  ! -path 'src/components/Money.tsx' \
  -exec grep -nE "$PATTERN" {} + | grep -v '<Money' || true)
if [ -n "$MATCHES" ]; then
  echo "$MATCHES"
  echo "FAIL: raw money field rendered without <Money> on the same line"
  FAIL=1
else
  echo "PASS: every money field access is wrapped in <Money>"
fi

if [ "$FAIL" -ne 0 ]; then
  echo ""
  echo "check-money: FAILED"
  exit 1
fi
echo ""
echo "check-money: all checks passed"
