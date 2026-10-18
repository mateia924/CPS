#!/usr/bin/env bash
set -euo pipefail

# Live-environment smoke test — sprint 5.0 (docs/CFO_REVIEW_1.md O8):
# proves the running stack actually serves CURRENT code over real HTTP,
# through nginx, exactly like a real user would hit it. This is the gap
# that let sprint 4.8's stale-gunicorn bug hide behind 229 passing
# pytest runs (pytest never touches the live container). Run this after
# every restart, before trusting the environment for UAT or real use —
# `make smoke` (see Makefile). Fails loudly and stops at the first
# broken step.
#
# Credentials: tenant/user default to the Accountant test user created
# during sprint 4's UAT run (docs/UAT_LOG.md) on tenant "fatma"; override
# with SMOKE_SUBDOMAIN/SMOKE_EMAIL. The password has NO default (rule 50,
# docs/SYSTEM_ANALYSIS.md §4): SMOKE_PASSWORD comes from the environment
# or the script stops before any request. Its value lives outside the
# repo, in /etc/cps-secrets/ (root:root 600) — never in this file. Until
# 2026-10-17 line 23 carried a buried default, published with the repo.

BASE_URL="${SMOKE_BASE_URL:-http://localhost:${HTTP_PORT:-3000}/api}"
SUBDOMAIN="${SMOKE_SUBDOMAIN:-fatma}"
EMAIL="${SMOKE_EMAIL:-accountant@fatma.test}"
PASSWORD="${SMOKE_PASSWORD:-}"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

fail() {
  echo "SMOKE TEST FAILED: $1" >&2
  exit 1
}

[ -n "$PASSWORD" ] || fail "SMOKE_PASSWORD is not set — smoke.sh has no default credential (rule 50, docs/SYSTEM_ANALYSIS.md §4). The value lives in /etc/cps-secrets/smoke_password: SMOKE_PASSWORD=\"\$(sudo cat /etc/cps-secrets/smoke_password)\" make smoke"

echo "[smoke] target: $BASE_URL (subdomain=$SUBDOMAIN, email=$EMAIL)"

echo "[smoke] POST /auth/login/"
LOGIN_STATUS="$(curl -s -o "$TMP_DIR/login.json" -w '%{http_code}' -X POST "$BASE_URL/auth/login/" \
  -H "Content-Type: application/json" \
  -d "{\"subdomain\":\"$SUBDOMAIN\",\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")"
[ "$LOGIN_STATUS" = "200" ] || fail "login returned $LOGIN_STATUS (expected 200) — body: $(cat "$TMP_DIR/login.json")"
ACCESS_TOKEN="$(python3 -c "import json; print(json.load(open('$TMP_DIR/login.json'))['access'])")" \
  || fail "login response had no access token: $(cat "$TMP_DIR/login.json")"
echo "[smoke] login OK"

echo "[smoke] GET /auth/me/"
ME_STATUS="$(curl -s -o "$TMP_DIR/me.json" -w '%{http_code}' \
  -H "Authorization: Bearer $ACCESS_TOKEN" "$BASE_URL/auth/me/")"
[ "$ME_STATUS" = "200" ] || fail "/auth/me/ returned $ME_STATUS (expected 200) — body: $(cat "$TMP_DIR/me.json")"
echo "[smoke] /auth/me/ OK (200)"

echo "[smoke] GET /invoices/"
INVOICES_STATUS="$(curl -s -o "$TMP_DIR/invoices.json" -w '%{http_code}' \
  -H "Authorization: Bearer $ACCESS_TOKEN" "$BASE_URL/invoices/")"
[ "$INVOICES_STATUS" = "200" ] || fail "/invoices/ returned $INVOICES_STATUS (expected 200) — body: $(cat "$TMP_DIR/invoices.json")"
echo "[smoke] /invoices/ OK (200)"

echo "[smoke] GET /journal-entries/trial_balance/"
TB_STATUS="$(curl -s -o "$TMP_DIR/tb.json" -w '%{http_code}' \
  -H "Authorization: Bearer $ACCESS_TOKEN" "$BASE_URL/journal-entries/trial_balance/")"
[ "$TB_STATUS" = "200" ] || fail "/journal-entries/trial_balance/ returned $TB_STATUS (expected 200) — body: $(cat "$TMP_DIR/tb.json")"
TB_MESSAGE="$(python3 -c "
import json
data = json.load(open('$TMP_DIR/tb.json'))
debit, credit = data['total_debit'], data['total_credit']
if debit != credit:
    print(f'FAIL:trial balance does not balance: debit={debit} credit={credit}')
else:
    print(f'OK:trial balance OK (debit=credit={debit})')
")"
case "$TB_MESSAGE" in
  OK:*) echo "[smoke] ${TB_MESSAGE#OK:}" ;;
  *) fail "${TB_MESSAGE#FAIL:}" ;;
esac

echo "[smoke] ALL CHECKS PASSED"
