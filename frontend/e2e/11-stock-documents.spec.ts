import { test, expect, type Page } from "@playwright/test";
import * as path from "path";

/** Sprint 7.4: إذن إضافة -> اعتماد -> ترحيل -> الرصيد يظهر في الشاشة ->
 * إذن صرف -> التقرير. A real click-through on the phase-1 smoke tenant —
 * nothing faked with page.route(). e2e.sh seeds what the screens can't
 * create yet (the inventory module flag, one warehouse, one stock item)
 * and turns off the tenant's default stock approval rules: the Owner is
 * the creator here and, with phase 3's second user active, could not
 * approve their own document — the approval path itself is covered by
 * the backend tests. "اعتماد" in this flow is the submit step's
 * auto-approval. */

const AUTH_DIR = path.join(__dirname, ".auth");
const ITEM_SKU = "E2E-STK-1";

test.use({ storageState: path.join(AUTH_DIR, "state.json") });

async function createAndPost(page: Page, slug: "receipts" | "issues", qty: string, unitCost?: string) {
  await page.goto(`/dashboard/inventory/stock/${slug}`);
  await page.waitForLoadState("networkidle"); // entities + warehouses loaded before reading the pickers
  const form = page.locator("form").first();
  const entitySelect = form.locator('[data-field="legal_entity"] select');
  if (await entitySelect.count()) {
    // Company + branch on the smoke tenant: the seeded warehouse is on the branch.
    const branch = await entitySelect.locator("option", { hasText: "MAIN-01" }).getAttribute("value");
    await entitySelect.selectOption(branch!);
  }
  await form.locator('[data-field="warehouse"] select').selectOption({ label: "E2E-W1 — مستودع e2e" });
  await form.locator('[data-field="lines.0.item"] input').fill(ITEM_SKU);
  await page.getByRole("option", { name: new RegExp(ITEM_SKU) }).click();
  await form.locator('[data-field="lines.0.qty"] input').fill(qty);
  if (unitCost) await form.locator('[data-field="lines.0.unit_cost"] input').fill(unitCost);
  await form.getByRole("button", { name: "حفظ كمسودة" }).click();

  await page.waitForURL(/\/dashboard\/inventory\/stock\/[0-9a-f-]{36}$/);
  await expect(page.getByText("مسودة").first()).toBeVisible();

  const submitted = page.waitForResponse((r) => r.url().includes("/submit/") && r.request().method() === "POST");
  await page.getByRole("button", { name: "إرسال للاعتماد" }).click();
  expect((await submitted).status()).toBe(200); // auto-approved — no active stock rule (see header)
  await expect(page.getByText("معتمدة").first()).toBeVisible();

  const posted = page.waitForResponse((r) => r.url().includes("/post/") && r.request().method() === "POST");
  await page.getByRole("button", { name: "ترحيل", exact: true }).click();
  expect((await posted).status()).toBe(200);
  await expect(page.getByText("مرحّلة").first()).toBeVisible();
  // Posted: no delete/edit button on screen (the API refusal itself is a backend test).
  await expect(page.getByRole("button", { name: "حذف", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "تعديل", exact: true })).toHaveCount(0);
}

async function balanceRow(page: Page) {
  await page.goto("/dashboard/inventory/balances");
  return page.getByRole("row", { name: new RegExp(ITEM_SKU) });
}

test("7.4: receipt -> approve -> post -> balance on screen -> issue -> report", async ({ page }) => {
  await createAndPost(page, "receipts", "10", "100");
  let row = await balanceRow(page);
  await expect(row.locator("td").nth(3)).toHaveText("10.00"); // الرصيد
  await expect(row.locator("td").nth(5)).toHaveText("1,000.00"); // القيمة
  await page.screenshot({ path: "../../docs/uat/screens/6.5.8/7.4-balance-after-receipt.png", fullPage: true });

  await createAndPost(page, "issues", "4");
  row = await balanceRow(page);
  await expect(row.locator("td").nth(3)).toHaveText("6.00");
  await expect(row.locator("td").nth(5)).toHaveText("600.00");
  await page.screenshot({ path: "../../docs/uat/screens/6.5.8/7.4-balance-after-issue.png", fullPage: true });
});
