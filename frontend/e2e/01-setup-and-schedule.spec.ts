import { test, expect, type Page } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

/** Sprint 6.5.8: real browser walkthrough of the UAT bug report — part
 * 1 registers a fresh smoke-* tenant, proves a normal voucher can post
 * to FIXED_ASSETS (decision C, sprint 6.5.6), then drives the
 * depreciation schedule through: a genuinely clean non-field error
 * (item 3), start -> withdraw -> restart (item 1), and the draft/
 * pending action set (item 2) — up to the point where approving needs
 * a second tenant user that no product UI can create yet (see
 * ../../backend/apps/accounts/management/commands/create_test_user.py
 * and the `e2e` Makefile target, which seeds it between this file and
 * 02-approve-and-generate.spec.ts). Saves browser storage state + the
 * asset id so part 2 can resume the same logged-in session. */

const SCREENSHOTS_DIR = path.join(__dirname, "../../docs/uat/screens/6.5.8");
const AUTH_DIR = path.join(__dirname, ".auth");
const SUBDOMAIN = process.env.E2E_SUBDOMAIN;
if (!SUBDOMAIN) throw new Error("E2E_SUBDOMAIN must be set (the `e2e` Makefile target sets it).");
const PASSWORD = "SmokeE2E!2026";

let shotIndex = 0;
async function shot(page: Page, name: string) {
  shotIndex += 1;
  await page.screenshot({
    path: path.join(SCREENSHOTS_DIR, `${String(shotIndex).padStart(2, "0")}-${name}.png`),
    fullPage: true,
  });
}

function field(page: Page, name: string) {
  return page.locator(`[data-field="${name}"]`).locator("input, select, textarea").first();
}

test("6.5.8 UAT part 1: register, approval rule, voucher on FIXED_ASSETS, asset, clean error, start/withdraw/restart", async ({
  page,
}) => {
  fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });
  fs.mkdirSync(AUTH_DIR, { recursive: true });

  await test.step("register a fresh smoke-* company", async () => {
    await page.goto("/register");
    await field(page, "company_name").fill("Smoke 658 UAT");
    await field(page, "subdomain").fill(SUBDOMAIN!);
    await field(page, "email").fill(`owner@${SUBDOMAIN}.test`);
    await field(page, "password").fill(PASSWORD);
    await page.getByRole("button", { name: "تسجيل شركة جديدة" }).click();
    await page.waitForURL("**/dashboard**");
    await shot(page, "register");
  });

  await test.step("create an approval rule for asset_depreciation (Owner, min 0)", async () => {
    // Without this, start-depreciation auto-approves (no matching
    // rule) and there is nothing to withdraw or approve below — also
    // exercises the E2E-discovered fix that this doc_type was missing
    // from the "create a new rule" picker entirely (settings/
    // approval-rules/page.tsx).
    await page.goto("/dashboard/settings/approval-rules");
    await field(page, "doc_type").selectOption("asset_depreciation");
    // Sprint 6.5.10 (item 3): role names render in Arabic now (roleLabel())
    // — "مالك", not the raw "Owner" Role.name.
    await field(page, "required_role").selectOption({ label: "مالك" });
    await page.getByRole("button", { name: "إضافة", exact: true }).click();
    await expect(page.locator("tr", { hasText: "جدول إهلاك أصل" })).toBeVisible();
    await shot(page, "approval-rule-created");
  });

  await test.step("create a cash box", async () => {
    await page.goto("/dashboard/treasury/cash-boxes");
    await field(page, "name").fill("صندوق E2E");
    await page.getByRole("button", { name: "إضافة", exact: true }).click();
    await expect(page.getByText("صندوق E2E").first()).toBeVisible();
    await shot(page, "cash-box-created");
  });

  await test.step("fund the cash box first (a fresh box has a zero balance — a receipt voucher, owner's equity)", async () => {
    await page.goto("/dashboard/treasury/vouchers/receipt");
    await field(page, "treasury_id").selectOption({ index: 1 });
    await field(page, "line_type").selectOption("account");
    const accountSelect = field(page, "account");
    const equityValue = await accountSelect
      .locator("option")
      .filter({ hasText: /^3100/ })
      .first()
      .getAttribute("value");
    await accountSelect.selectOption(equityValue!);
    await field(page, "amount_fc").fill("20000");
    await page.getByRole("button", { name: "سند قبض جديد" }).click();
    await expect(page.getByText("مسودة").first()).toBeVisible();
    await page.getByRole("button", { name: "ترحيل" }).click();
    await expect(page.getByText("مسودة")).toHaveCount(0);
    await shot(page, "receipt-voucher-funded-cash-box");
  });

  await test.step("post a 12,000 payment voucher directly to FIXED_ASSETS (decision C)", async () => {
    await page.goto("/dashboard/treasury/vouchers/payment");
    await field(page, "treasury_id").selectOption({ index: 1 });
    await field(page, "line_type").selectOption("account");
    const accountSelect = field(page, "account");
    const fixedAssetsValue = await accountSelect
      .locator("option")
      .filter({ hasText: /^1700/ })
      .first()
      .getAttribute("value");
    await accountSelect.selectOption(fixedAssetsValue!);
    await field(page, "amount_fc").fill("12000");
    await page.getByRole("button", { name: "سند صرف جديد" }).click();
    await expect(page.getByText("مسودة").first()).toBeVisible();
    await shot(page, "voucher-created");

    await page.getByRole("button", { name: "ترحيل" }).click();
    await expect(page.getByText("مسودة")).toHaveCount(0);
    await shot(page, "voucher-posted");
  });

  const assetId = await test.step("create the asset, not depreciable on purpose (item 1: the field is basic now, and required only when depreciable)", async () => {
    await page.goto("/dashboard/assets");
    await field(page, "code").fill("AST-E2E");
    await field(page, "name").fill("أصل اختبار E2E");
    await field(page, "purchase_date").fill("2026-08-01");
    await field(page, "purchase_cost").fill("12000");
    // Sprint 6.5.10 (item 1): useful_life_months/salvage_value/
    // is_depreciable moved to the basic section, and the first is now
    // `required` client-side whenever is_depreciable is checked (the
    // default) — so leaving it blank the way this test used to (to
    // reach the same backend validation error for item 3 below) would
    // just be blocked by the browser itself. Unchecking "قابل للإهلاك"
    // here instead legitimately leaves it blank AND exercises the new
    // checkbox itself.
    await page.getByRole("checkbox", { name: "قابل للإهلاك" }).uncheck();
    await page.getByRole("button", { name: "إضافة", exact: true }).click();
    await expect(page.getByText("AST-E2E").first()).toBeVisible();
    await shot(page, "asset-created");

    const row = page.locator("tr", { hasText: "AST-E2E" });
    await row.getByRole("link", { name: "عرض التفاصيل" }).click();
    await page.waitForURL("**/dashboard/assets/*");
    await shot(page, "asset-detail");
    return page.url().split("/").filter(Boolean).pop()!;
  });

  await test.step("item 3: a real non-field error renders clean text, no Python list brackets", async () => {
    // is_depreciable=false on this asset -> start_depreciation raises
    // a plain django ValidationError ("هذا الأصل لا يُهلك."), caught as
    // {"detail": str(exc)} — before the fix this reached the UI as
    // "['هذا الأصل لا يُهلك.']" verbatim.
    await page.getByRole("button", { name: "بدء الإهلاك" }).click();
    const banner = page.getByTestId("warnings-banner-error");
    await expect(banner).toContainText("هذا الأصل لا يُهلك");
    await expect(banner).not.toContainText("[");
    await expect(banner).not.toContainText("]");
    await shot(page, "clean-error-no-brackets");
  });

  await test.step("fix the asset (is_depreciable=true, useful_life_months=12) via the edit action", async () => {
    await page.goto("/dashboard/assets");
    const row = page.locator("tr", { hasText: "AST-E2E" });
    await row.getByRole("button", { name: "تعديل" }).click();
    await page.getByRole("checkbox", { name: "قابل للإهلاك" }).check();
    await field(page, "useful_life_months").fill("12");
    await page.getByRole("button", { name: "حفظ التعديلات" }).click();
    await shot(page, "asset-edited");

    await row.getByRole("link", { name: "عرض التفاصيل" }).click();
    await page.waitForURL(`**/dashboard/assets/${assetId}`);
  });

  await test.step("item 1/2: start depreciation -> pending approval, remaining months shows —", async () => {
    await page.getByRole("button", { name: "بدء الإهلاك" }).click();
    await expect(page.getByText("بانتظار الاعتماد").first()).toBeVisible();
    // item 5: the remaining-months card must read "—" before approval,
    // not a misleading 0.
    await expect(page.locator(".card", { hasText: "الأشهر المتبقية" }).last()).toContainText("—");
    await shot(page, "started-pending-approval");
  });

  await test.step("item 1: withdraw fully cancels and frees the asset for a fresh start", async () => {
    await page.getByRole("button", { name: "سحب", exact: true }).click();
    await expect(page.getByText("لا يوجد جدول إهلاك لهذا الأصل")).toBeVisible();
    await shot(page, "withdrawn-form-editable-again");
  });

  await test.step("restart with opening_accumulated_depreciation=0 explicitly, lands pending again", async () => {
    await field(page, "opening_accumulated_depreciation").fill("0");
    await page.getByRole("button", { name: "بدء الإهلاك" }).click();
    await expect(page.getByText("بانتظار الاعتماد").first()).toBeVisible();
    await shot(page, "restarted-pending-approval");
  });

  await page.context().storageState({ path: path.join(AUTH_DIR, "state.json") });
  fs.writeFileSync(path.join(AUTH_DIR, "context.json"), JSON.stringify({ subdomain: SUBDOMAIN, assetId }, null, 2));
});
