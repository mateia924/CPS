#!/usr/bin/env bash
set -euo pipefail

# Block 8.0.1: frontend/e2e/14-screen-access.spec.ts on a tenant of its
# own, against the dev stack (`make dev-up` first) — runnable alone, so
# scripts/prove_guard.sh --e2e can run it with a guard disabled without
# the whole of scripts/e2e.sh around it.
#
# Builds a fresh smoke-* tenant through the real registration API, turns
# the purchasing module on (no screen does that yet), adds a Viewer (no
# purchasing.view) with create_test_user, runs the spec as that Viewer,
# and archives the tenant on every exit. Never touches a real tenant.
#
# Usage: scripts/e2e_access.sh [SPEC]   (default 14-screen-access.spec.ts)
# The spec gets E2E_SUBDOMAIN, the Viewer's E2E_VIEWER_EMAIL/_PASSWORD and
# the Owner's E2E_OWNER_EMAIL/_PASSWORD (8.1's walk, 15-supplier-bills).
# E2E_CONTAINER_NAME names the Playwright container (prove_guard.sh uses
# it to remove the container if it is interrupted).

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

SPEC="${1:-14-screen-access.spec.ts}"
PLAYWRIGHT_IMAGE="mcr.microsoft.com/playwright:v1.63.0-noble"  # = frontend/package.json, see e2e.sh
API_URL="$(grep '^DEV_NEXT_PUBLIC_API_URL=' .env | cut -d= -f2-)"
BASE_URL="${API_URL%/api}"
SUBDOMAIN="smoke-access-$(date +%s)"
# Rule 50: no literal password in a script and none on a command line.
# Fresh per run, handed on through the environment (`-e NAME`) or stdin.
export E2E_OWNER_PASSWORD="Ow1!$(od -An -N12 -tx1 /dev/urandom | tr -d ' \n')"
export E2E_VIEWER_PASSWORD="Vw1!$(od -An -N12 -tx1 /dev/urandom | tr -d ' \n')"
VIEWER_EMAIL="viewer@$SUBDOMAIN.test"
CONTAINER_NAME="${E2E_CONTAINER_NAME:-cps-e2e-access-$$}"

cleanup() {
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
  docker exec cps-dev-backend-1 python manage.py archive_smoke_tenants \
    --force --reason "e2e_access.sh: disposable smoke tenant this run created" >/dev/null 2>&1 \
    && echo "[e2e-access] archived smoke tenants" || echo "[e2e-access] WARNING: archive_smoke_tenants failed" >&2
}
trap cleanup EXIT

echo "[e2e-access] target: $BASE_URL (subdomain=$SUBDOMAIN)"
code="$(printf '{"company_name": "Smoke access", "subdomain": "%s", "email": "owner@%s.test", "password": "%s"}' \
    "$SUBDOMAIN" "$SUBDOMAIN" "$E2E_OWNER_PASSWORD" \
  | curl -s -o /dev/null -w '%{http_code}' -X POST "$API_URL/auth/register/" \
    -H 'Content-Type: application/json' --data-binary @-)"
[ "$code" = "201" ] || { echo "[e2e-access] registration returned HTTP $code, expected 201" >&2; exit 1; }

docker exec cps-dev-backend-1 python manage.py shell -c "
from apps.tenants.models import Tenant
t = Tenant.objects.get(subdomain='$SUBDOMAIN')
assert not t.features.purchasing, 'purchasing already on for a fresh tenant'
t.features.purchasing = True
t.features.save(update_fields=['purchasing'])
print('[e2e-access] purchasing module on')
"
docker exec -e E2E_VIEWER_PASSWORD cps-dev-backend-1 python manage.py shell -c "
import os
from django.core.management import call_command
call_command('create_test_user', subdomain='$SUBDOMAIN', email='$VIEWER_EMAIL', password=os.environ['E2E_VIEWER_PASSWORD'], role='Viewer')
"
docker exec cps-dev-backend-1 python manage.py shell -c "
from apps.accounts.models import User
u = User.objects.get(email='$VIEWER_EMAIL')
codes = set(u.roles.values_list('permissions__code', flat=True))
assert 'purchasing.view' not in codes and 'parties.view' in codes, sorted(codes)
print('[e2e-access] viewer holds parties.view, not purchasing.view')
"

docker run --rm --name "$CONTAINER_NAME" --network host \
  -e E2E_BASE_URL="$BASE_URL" -e E2E_SUBDOMAIN="$SUBDOMAIN" \
  -e E2E_VIEWER_EMAIL="$VIEWER_EMAIL" -e E2E_VIEWER_PASSWORD \
  -e E2E_OWNER_EMAIL="owner@$SUBDOMAIN.test" -e E2E_OWNER_PASSWORD \
  -v "$ROOT_DIR:/repo" -w /repo/frontend/e2e \
  "$PLAYWRIGHT_IMAGE" \
  sh -c "npx playwright test '$SPEC' --reporter=list"
