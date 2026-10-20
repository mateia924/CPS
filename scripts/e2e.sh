#!/usr/bin/env bash
set -euo pipefail

# Sprint 6.5.8 (docs/CPS_MASTER_PLAN.md §9.3, "الكتل التي تلمس الواجهة"):
# a real headless-browser click-through against the running dev stack
# (`make dev-up` first), not an API-level check — the official
# mcr.microsoft.com/playwright Docker image (this repo's own frontend
# image is Alpine/musl, which cannot run Playwright's Chromium build at
# all) with --network host so it can reach nginx exactly like a real
# browser would. Always on a fresh smoke-* tenant it creates and
# archives itself; never touches a real tenant.
#
# Two phases sharing one browser session (frontend/e2e/.auth/state.json)
# because part of this scenario (a genuinely blocked-but-emergency-
# eligible approval) needs a second tenant user, and there is currently
# no product UI to add one — see backend/apps/accounts/management/
# commands/create_test_user.py's own docstring for that gap. A future
# scenario that doesn't need this can just be its own single-phase spec
# file; nothing here requires every spec to follow this two-phase shape.

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

# Sprint 6.6.3c: must match frontend/package.json's own @playwright/test
# version exactly — this image's bundled browser binaries are built
# for that exact release; any mismatch is a silent "works on my
# machine" risk, not just a version-number nicety.
PLAYWRIGHT_IMAGE="mcr.microsoft.com/playwright:v1.63.0-noble"
# Sprint 6.6.0: `make dev-up` now serves the interactive sandbox on
# port 3002 (DEV_NEXT_PUBLIC_API_URL), not port 3000 (NEXT_PUBLIC_API_URL
# is the local/live stack scripts/deploy.sh manages, on its own compose
# project "infra" — never what this suite exercises) — this keeps the
# original intent (test against whatever `make dev-up` just brought up)
# unchanged, only the variable name moved.
API_URL="$(grep '^DEV_NEXT_PUBLIC_API_URL=' .env | cut -d= -f2-)"
BASE_URL="${API_URL%/api}"
SCREENS_DIR="docs/uat/screens/6.5.8"
SUBDOMAIN="smoke-$(date +%s)"

echo "[e2e] target: $BASE_URL (subdomain=$SUBDOMAIN)"
rm -f "$SCREENS_DIR"/*.png
mkdir -p "$SCREENS_DIR"

# Sprint 7.0.3 follow-up (found 2026-10-04 via `make ci-local`, which
# is exactly what it's for): archive_smoke_tenants now refuses to
# archive a tenant carrying a POSTED, never-reversed JournalEntry —
# and every scenario this suite runs (vouchers, asset entries, etc.)
# deliberately posts real entries it never reverses, since the whole
# point of archiving here is throwing the tenant away, not closing
# its books. Without --force --reason, this call (and the one at the
# end of this script) now fails every single run, deterministically —
# not a flake. --reason is logged to AuditLog, same as any other
# --force use; this is the one place in the whole project where
# leaving real posted debt behind on archive is the INTENDED, accepted
# outcome, not a lapse to be caught.
echo "[e2e] archiving any leftover smoke-* tenants first"
docker exec cps-dev-backend-1 python manage.py archive_smoke_tenants \
  --force --reason "e2e.sh: disposable smoke tenant from a previous run, never meant to be reversed"

echo "[e2e] phase 1: register, approval rule, voucher, asset, clean error, start/withdraw/restart"
# Sprint 6.6.3c: @playwright/test lives in frontend/package.json now
# (one lockfile, one gate — no nested frontend/e2e/package.json of its
# own) — `npm install` here runs against the ROOT package.json/
# package-lock.json; node's own module resolution then finds
# frontend/node_modules/@playwright/test from frontend/e2e just fine
# (climbs parent directories, same as every other node_modules lookup).
docker run --rm --network host \
  -e E2E_SUBDOMAIN="$SUBDOMAIN" -e E2E_BASE_URL="$BASE_URL" \
  -v "$ROOT_DIR:/repo" -w /repo/frontend \
  "$PLAYWRIGHT_IMAGE" \
  sh -c "npm install --no-audit --no-fund && cd e2e && npx playwright test 01-setup-and-schedule.spec.ts --reporter=list"

echo "[e2e] seeding a second (Accountant) user for the emergency-approval scenario"
# Rule 50: the password goes through the environment, never on the
# command line; nothing logs in as this user, so it is random per run.
export E2E_TEST_USER_PASSWORD="Ac1!$(od -An -N12 -tx1 /dev/urandom | tr -d ' \n')"
docker exec -e E2E_TEST_USER_PASSWORD cps-dev-backend-1 python manage.py create_test_user \
  --subdomain "$SUBDOMAIN" --email "accountant@$SUBDOMAIN.test" --role Accountant

echo "[e2e] phase 2: emergency-approval prompt, generate due now"
docker run --rm --network host \
  -e E2E_BASE_URL="$BASE_URL" \
  -v "$ROOT_DIR:/repo" -w /repo/frontend/e2e \
  "$PLAYWRIGHT_IMAGE" \
  sh -c "npx playwright test 02-approve-and-generate.spec.ts --reporter=list"

# Sprint 6.5.10 (item 6): genuine creator != approver — this phase
# creates its own second user through the "مستخدم جديد" UI (not
# create_test_user, which exists only for phase 2's emergency scenario
# above), so it needs no extra backend seeding step of its own. It DOES
# need phase 2's seeded Accountant out of the way first, though: the
# Free plan's own max_users=2 (Owner + that seeded Accountant already
# fills it) would otherwise 402 phase 3's own user-creation step — a
# real plan-limit collision between two independent scenarios sharing
# one tenant, not a bug in either. Deactivating (never deleting) frees
# the seat; phase 2 is already done with it by this point.
echo "[e2e] deactivating phase 2's seeded Accountant to free a seat under the Free plan's max_users=2"
docker exec cps-dev-backend-1 python manage.py shell -c "
from apps.accounts.models import User
User.objects.filter(tenant__subdomain='$SUBDOMAIN', email='accountant@$SUBDOMAIN.test').update(is_active=False)
"

echo "[e2e] phase 3: real (non-emergency) approval by a second user made through the UI"
docker run --rm --network host \
  -e E2E_BASE_URL="$BASE_URL" \
  -v "$ROOT_DIR:/repo" -w /repo/frontend/e2e \
  "$PLAYWRIGHT_IMAGE" \
  sh -c "npx playwright test 03-non-emergency-approval.spec.ts --reporter=list"

echo "[e2e] phase 4: raw non-JSON API responses never leak HTML — unified message on login and an authenticated screen"
docker run --rm --network host \
  -e E2E_BASE_URL="$BASE_URL" \
  -v "$ROOT_DIR:/repo" -w /repo/frontend/e2e \
  "$PLAYWRIGHT_IMAGE" \
  sh -c "npx playwright test 04-server-error-message.spec.ts --reporter=list"

echo "[e2e] phase 5: a 400 on a field hidden inside a collapsed 'متقدم' section still reaches the general banner"
docker run --rm --network host \
  -e E2E_BASE_URL="$BASE_URL" \
  -v "$ROOT_DIR:/repo" -w /repo/frontend/e2e \
  "$PLAYWRIGHT_IMAGE" \
  sh -c "npx playwright test 05-hidden-field-error.spec.ts --reporter=list"

echo "[e2e] phase 6: balance sheet screen shows the balanced check line"
docker run --rm --network host \
  -e E2E_BASE_URL="$BASE_URL" \
  -v "$ROOT_DIR:/repo" -w /repo/frontend/e2e \
  "$PLAYWRIGHT_IMAGE" \
  sh -c "npx playwright test 06-balance-sheet-check-line.spec.ts --reporter=list"

echo "[e2e] phase 7: array-shaped detail on a failed voucher post shows verbatim, not the generic fallback"
docker run --rm --network host \
  -e E2E_BASE_URL="$BASE_URL" \
  -v "$ROOT_DIR:/repo" -w /repo/frontend/e2e \
  "$PLAYWRIGHT_IMAGE" \
  sh -c "npx playwright test 07-voucher-insufficient-balance-message.spec.ts --reporter=list"

echo "[e2e] phase 8: approval inbox hides Approve for a document the user created themselves"
docker run --rm --network host \
  -e E2E_BASE_URL="$BASE_URL" \
  -v "$ROOT_DIR:/repo" -w /repo/frontend/e2e \
  "$PLAYWRIGHT_IMAGE" \
  sh -c "npx playwright test 08-approval-inbox-own-document-hidden.spec.ts --reporter=list"

echo "[e2e] phase 9: asset transfer log shows an ISO date, never a US-locale one"
docker run --rm --network host \
  -e E2E_BASE_URL="$BASE_URL" \
  -v "$ROOT_DIR:/repo" -w /repo/frontend/e2e \
  "$PLAYWRIGHT_IMAGE" \
  sh -c "npx playwright test 09-asset-transfer-log-date-format.spec.ts --reporter=list"

# Block 8.2.1: spec 10 existed since 7.2.9 (44253ac) and no runner ran it.
# It needs a host with a tenant label in front, and BASE_URL is a bare IP
# here and in CI (`fatma.<ip>` is not a URL: "Cannot navigate to invalid
# URL"), so it runs against localhost on the same port — `*.localhost`
# resolves to loopback in Chromium (RFC 6761). Frontend-only: the confirm
# endpoint is faked in the spec, no request reaches any tenant.
echo "[e2e] phase 10: reset-password on a tenant host sends the host's subdomain with the field hidden"
docker run --rm --network host \
  -e E2E_BASE_URL="http://localhost:$(echo "$BASE_URL" | sed -E 's#^https?://[^:/]+:?([0-9]*).*#\1#;s#^$#80#')" \
  -v "$ROOT_DIR:/repo" -w /repo/frontend/e2e \
  "$PLAYWRIGHT_IMAGE" \
  sh -c "npx playwright test 10-reset-password-subdomain-from-host.spec.ts --reporter=list"

# Sprint 7.4: stock documents. Seeds only what no screen creates yet on a
# fresh smoke tenant — the inventory module flag, one warehouse on the
# branch, one stock item. No approval rule is touched here: registration
# seeds the default stock_* rules (apps/approvals/defaults.py), the spec
# re-points receipt/issue to Accountant through the approval-rules screen,
# and phase 3's second user (frontend/e2e/.auth/second-user.json) approves
# what the Owner created. Never touches a real tenant.
echo "[e2e] seeding inventory for the stock-documents scenario"
docker exec cps-dev-backend-1 python manage.py shell -c "
from apps.inventory.models import Warehouse
from apps.organization.models import LegalEntity
from apps.sales.models import Product
from apps.tenants.models import Tenant
t = Tenant.objects.get(subdomain='$SUBDOMAIN')
t.features.inventory = True
t.features.save(update_fields=['inventory'])
branch = LegalEntity.objects.get(tenant=t, code='MAIN-01')
Warehouse.objects.get_or_create(tenant=t, code='E2E-W1', defaults={'legal_entity': branch, 'name': 'مستودع e2e'})
Product.objects.get_or_create(tenant=t, sku='E2E-STK-1', defaults={'name': 'صنف مخزني e2e', 'unit_price': '150.00', 'tax_rate': '15.00', 'item_type': 'stock'})
"

echo "[e2e] phase 11: stock receipt -> approve (second user) -> post -> balance on screen -> issue -> report"
docker run --rm --network host \
  -e E2E_BASE_URL="$BASE_URL" \
  -v "$ROOT_DIR:/repo" -w /repo/frontend/e2e \
  "$PLAYWRIGHT_IMAGE" \
  sh -c "npx playwright test 11-stock-documents.spec.ts --reporter=list"

# Sprint 7.5 follow-up: count sessions (the D16 path end to end). Seeds
# the one thing no screen creates yet — a serial-tracked stock item; its
# serials come in on a receipt the spec itself posts over HTTP. The serial
# statuses and the reconciliation invariant aren't exposed over HTTP, so
# they are checked here, in the database, after each of the two tests —
# every check asserts and prints its numbers.
echo "[e2e] seeding a serial-tracked item for the count scenario"
docker exec cps-dev-backend-1 python manage.py shell -c "
from apps.sales.models import Product
from apps.tenants.models import Tenant
t = Tenant.objects.get(subdomain='$SUBDOMAIN')
item, created = Product.objects.get_or_create(tenant=t, sku='E2E-SER-1', defaults={'name': 'صنف بسيريال e2e', 'unit_price': '900.00', 'tax_rate': '15.00', 'item_type': 'stock', 'tracking': 'serial'})
assert created and item.tracking == 'serial', 'E2E-SER-1 already existed on a fresh smoke tenant'
print('[e2e] seeded E2E-SER-1 (serial)')
"

count_check() {
  # args: label, expected serial statuses, expected ItemCost (E2E-STK-1), expected ItemCost (E2E-SER-1)
  docker exec cps-dev-backend-1 python manage.py shell -c "
from decimal import Decimal as D
from django.db.models import Sum
from apps.accounting.models import JournalLine
from apps.accounting.services import REPORTABLE_STATUSES
from apps.inventory.models import ItemCost, SerialNumber, StockMove
from apps.tenants.models import Tenant
t = Tenant.objects.get(subdomain='$SUBDOMAIN')
statuses = dict(SerialNumber.objects.filter(tenant=t, item__sku='E2E-SER-1').values_list('serial', 'status'))
costs = {c.item.sku: (str(c.qty_on_hand), str(c.total_value), str(c.avg_cost)) for c in ItemCost.objects.filter(tenant=t).select_related('item')}
def bal(key):
    s = JournalLine.objects.filter(entry__tenant=t, entry__status__in=REPORTABLE_STATUSES, account__system_key=key).aggregate(d=Sum('debit'), c=Sum('credit'))
    return (s['d'] or D(0)) - (s['c'] or D(0))
ledger = bal('INVENTORY')
item_costs = ItemCost.objects.filter(tenant=t).aggregate(v=Sum('total_value'))['v']
moves = StockMove.objects.filter(tenant=t).aggregate(v=Sum('value'))['v']
print('[e2e] $1: serials', statuses)
print('[e2e] $1: ItemCost', costs)
print('[e2e] $1: INVENTORY ledger', ledger, '| sum ItemCost.total_value', item_costs, '| sum StockMove.value', moves, '| INVENTORY_ADJUSTMENT', bal('INVENTORY_ADJUSTMENT'))
assert statuses == $2, statuses
assert costs['E2E-STK-1'] == $3, costs
assert costs['E2E-SER-1'] == $4, costs
assert ledger == item_costs == moves, (ledger, item_costs, moves)
print('[e2e] $1: reconciled')
"
}

echo "[e2e] phase 12: count session — open, count (shortage + surplus at an entered cost), approve (second user), post, trial balance"
docker run --rm --network host \
  -e E2E_BASE_URL="$BASE_URL" \
  -v "$ROOT_DIR:/repo" -w /repo/frontend/e2e \
  "$PLAYWRIGHT_IMAGE" \
  sh -c "npx playwright test 12-stock-count.spec.ts --grep 'trial balance' --reporter=list"
count_check "after post" \
  "{'E2E-SN-1': 'in_stock', 'E2E-SN-2': 'in_stock', 'E2E-SN-3': 'disposed'}" \
  "('8.00', '740.00', '92.5000')" "('2.00', '1000.00', '500.0000')"

echo "[e2e] phase 12: reversing the count — serials back in stock, averages back"
docker run --rm --network host \
  -e E2E_BASE_URL="$BASE_URL" \
  -v "$ROOT_DIR:/repo" -w /repo/frontend/e2e \
  "$PLAYWRIGHT_IMAGE" \
  sh -c "npx playwright test 12-stock-count.spec.ts --grep 'reversing' --reporter=list"
count_check "after reverse" \
  "{'E2E-SN-1': 'in_stock', 'E2E-SN-2': 'in_stock', 'E2E-SN-3': 'in_stock'}" \
  "('6.00', '600.00', '100.0000')" "('3.00', '1500.00', '500.0000')"

# Sprint 8.0: purchasing settings + withholding codes as registration
# seeded them. No screen turns the module on yet, so this does.
echo "[e2e] enabling the purchasing module for phase 13"
docker exec cps-dev-backend-1 python manage.py shell -c "
from apps.tenants.models import Tenant
t = Tenant.objects.get(subdomain='$SUBDOMAIN')
t.features.purchasing = True
t.features.save(update_fields=['purchasing'])
"

echo "[e2e] phase 13: purchasing settings — withholding codes carry the examples badge, tolerance saves, supplier-bill rule named"
docker run --rm --network host \
  -e E2E_BASE_URL="$BASE_URL" \
  -v "$ROOT_DIR:/repo" -w /repo/frontend/e2e \
  "$PLAYWRIGHT_IMAGE" \
  sh -c "npx playwright test 13-purchasing-settings.spec.ts --reporter=list"

echo "[e2e] archiving the smoke-* tenant this run created"
docker exec cps-dev-backend-1 python manage.py archive_smoke_tenants \
  --force --reason "e2e.sh: disposable smoke tenant this run created, never meant to be reversed"

# Block 8.0.1: sidebar gating and the shell's no-permission state, as a
# Viewer. Its own tenant (it needs a second user and the purchasing
# module on), built and archived by e2e_access.sh — after the archive
# above, since that script archives every smoke-* tenant on exit.
echo "[e2e] phase 14: no sidebar link the user cannot open; a refused screen names the reason"
"$ROOT_DIR/scripts/e2e_access.sh" 14-screen-access.spec.ts

# Sprint 8.1: supplier bills and the expenses list, every record entered
# through the UI on a tenant of its own (same script, the Owner's login).
echo "[e2e] phase 15: supplier bills (rent/telecoms/RC/asset), duplicate number, attachment rule, expenses"
"$ROOT_DIR/scripts/e2e_access.sh" 15-supplier-bills.spec.ts

# Block 8.0.2: 404 / JSON 500 / HTML 500 each render a named state; a list
# never renders a failure as an empty result.
echo "[e2e] phase 16: named error states — API 404, JSON 500, HTML 500 on three lists"
"$ROOT_DIR/scripts/e2e_access.sh" 16-error-states.spec.ts

# Sprint 8.2: paying supplier bills — partial payment from the bill, an
# advance applied, «دفع نقدي الآن», payables aging / statement / weekly,
# each report also with its API forced to fail.
echo "[e2e] phase 17: supplier payments, advances, pay now, payables aging, statement, weekly payables"
"$ROOT_DIR/scripts/e2e_access.sh" 17-supplier-payments.spec.ts

echo "[e2e] ALL CHECKS PASSED — screenshots in $SCREENS_DIR/"
