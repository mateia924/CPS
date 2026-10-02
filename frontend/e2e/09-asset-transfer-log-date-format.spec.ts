import { test, expect } from "@playwright/test";
import * as path from "path";

/** Sprint 6.6.6 (item 1, the block's own motivating bug): the asset
 * transfer log rendered `new Date(transfer.created_at).
 * toLocaleDateString()` with no locale argument — correct-looking in
 * whatever locale the DEVELOPER's own browser happened to be in, but
 * on a US-locale viewer this showed "1/2/2026" instead of this
 * project's own ISO `YYYY-MM-DD` table convention. lib/date.ts's
 * formatDate() fixes it project-wide; this proves it end to end on
 * the exact screen the live bug was found on. Reuses phase 1's saved
 * Owner session — no real asset/transfer state needed, both are
 * faked via page.route(). */

const AUTH_DIR = path.join(__dirname, ".auth");

test.use({ storageState: path.join(AUTH_DIR, "state.json") });

const ENTITY_A = "33333333-0000-0000-0000-000000000001";
const ENTITY_B = "33333333-0000-0000-0000-000000000002";
const ASSET_ID = "33333333-1111-1111-1111-111111111111";

test("6.6.6 item 1: the transfer log shows an ISO date, never a US-locale one", async ({ page }) => {
  const fakeAsset = {
    id: ASSET_ID, legal_entity: ENTITY_B, code: "FA-0099", name: "أصل اختبار سجل النقل",
    category: "equipment", purchase_date: "2026-01-01", purchase_cost: "1000.00", currency: "SAR",
    useful_life_months: 12, salvage_value: "0.00", depreciation_method: "straight_line",
    custodian: null, cost_center: null, status: "active", is_active: true, created_at: "2026-01-01T00:00:00Z",
    is_depreciable: true, purchase_reference: "", in_service_date: "2026-01-01", cost_base: "1000.00",
    salvage_base: "0.00", opening_accumulated_depreciation: "0.00", declining_balance_rate: null,
    disposed_fraction: "0.0000", depreciation_entry: null, additions: [], accumulated_depreciation: "0.00",
    book_value: "1000.00", disposals: [],
    transfers: [
      {
        id: "33333333-2222-2222-2222-222222222222",
        from_legal_entity: ENTITY_A, to_legal_entity: ENTITY_B,
        from_cost_center: null, to_cost_center: null,
        reason: "نقل اختبار", created_by: null,
        // Jan 2nd — day != month, so a US-locale `toLocaleDateString()`
        // ("1/2/2026") is unambiguously distinguishable from the
        // correct ISO table format ("2026-01-02").
        created_at: "2026-01-02T10:00:00Z",
      },
    ],
    historical_installments: [],
  };

  await page.route(`**/api/assets/${ASSET_ID}/`, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(fakeAsset) })
  );
  await page.route("**/api/accounts/tree/", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) })
  );
  await page.route("**/api/legal-entities/**", (route) =>
    route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({
        count: 2, next: null, previous: null,
        results: [
          { id: ENTITY_A, code: "HQ", name: "الإدارة" },
          { id: ENTITY_B, code: "BR1", name: "الفرع الأول" },
        ],
      }),
    })
  );
  await page.route("**/api/cost-centers/**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ count: 0, next: null, previous: null, results: [] }) })
  );

  await page.goto(`/dashboard/assets/${ASSET_ID}`);
  await expect(page.getByText("2026-01-02")).toBeVisible();
  await expect(page.getByText("1/2/2026")).not.toBeVisible();
});
