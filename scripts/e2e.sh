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

PLAYWRIGHT_IMAGE="mcr.microsoft.com/playwright:v1.49.1-noble"
API_URL="$(grep '^NEXT_PUBLIC_API_URL=' .env | cut -d= -f2-)"
BASE_URL="${API_URL%/api}"
SCREENS_DIR="docs/uat/screens/6.5.8"
SUBDOMAIN="smoke-$(date +%s)"

echo "[e2e] target: $BASE_URL (subdomain=$SUBDOMAIN)"
rm -f "$SCREENS_DIR"/*.png
mkdir -p "$SCREENS_DIR"

echo "[e2e] archiving any leftover smoke-* tenants first"
docker exec infra-backend-1 python manage.py archive_smoke_tenants

echo "[e2e] phase 1: register, approval rule, voucher, asset, clean error, start/withdraw/restart"
docker run --rm --network host \
  -e E2E_SUBDOMAIN="$SUBDOMAIN" -e E2E_BASE_URL="$BASE_URL" \
  -v "$ROOT_DIR:/repo" -w /repo/frontend/e2e \
  "$PLAYWRIGHT_IMAGE" \
  sh -c "npm install --no-audit --no-fund && npx playwright test 01-setup-and-schedule.spec.ts --reporter=list"

echo "[e2e] seeding a second (Accountant) user for the emergency-approval scenario"
docker exec infra-backend-1 python manage.py create_test_user \
  --subdomain "$SUBDOMAIN" --email "accountant@$SUBDOMAIN.test" --password "SmokeE2E!2026" --role Accountant

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
docker exec infra-backend-1 python manage.py shell -c "
from apps.accounts.models import User
User.objects.filter(tenant__subdomain='$SUBDOMAIN', email='accountant@$SUBDOMAIN.test').update(is_active=False)
"

echo "[e2e] phase 3: real (non-emergency) approval by a second user made through the UI"
docker run --rm --network host \
  -e E2E_BASE_URL="$BASE_URL" \
  -v "$ROOT_DIR:/repo" -w /repo/frontend/e2e \
  "$PLAYWRIGHT_IMAGE" \
  sh -c "npx playwright test 03-non-emergency-approval.spec.ts --reporter=list"

echo "[e2e] archiving the smoke-* tenant this run created"
docker exec infra-backend-1 python manage.py archive_smoke_tenants

echo "[e2e] ALL CHECKS PASSED — screenshots in $SCREENS_DIR/"
