import { test, expect, type Browser, type Page } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

/** Sprint 7.4: إذن إضافة -> اعتماد -> ترحيل -> الرصيد يظهر في الشاشة ->
 * إذن صرف -> التقرير. A real click-through on the phase-1 smoke tenant —
 * nothing faked with page.route(). e2e.sh seeds what the screens can't
 * create yet (the inventory module flag, one warehouse, one stock item).
 *
 * Approval is walked, not switched off. Registration seeds the default
 * stock rules (min=0 -> Owner, apps/approvals/defaults.py); the spec
 * re-points receipt and issue to Accountant through the approval-rules
 * screen, since the only Owner is the creator. Then: the Owner creates and submits (202,
 * PENDING_APPROVAL), the Owner's own approve is refused with 403
 * (creator, and another active user holds the role, so no emergency
 * path), and phase 3's second user — the Accountant made through the
 * UI, credentials left in .auth/second-user.json — approves in its own
 * browser context before the Owner posts. */

const AUTH_DIR = path.join(__dirname, ".auth");
const ITEM_SKU = "E2E-STK-1";
const context = JSON.parse(fs.readFileSync(path.join(AUTH_DIR, "context.json"), "utf-8"));
const SUBDOMAIN: string = context.subdomain;
const secondUser: { email: string; password: string } = JSON.parse(
  fs.readFileSync(path.join(AUTH_DIR, "second-user.json"), "utf-8")
);

test.use({ storageState: path.join(AUTH_DIR, "state.json") });

function field(page: Page, name: string) {
  return page.locator(`[data-field="${name}"]`).locator("input, select, textarea").first();
}

async function requireAccountantOn(page: Page, docTypeLabel: string) {
  // Edits the rule registration seeded (min=0 -> Owner) — the same move
  // phase 3 makes on asset_depreciation.
  await page.goto("/dashboard/settings/approval-rules");
  const row = page.locator("tr", { hasText: docTypeLabel });
  await expect(row).toHaveCount(1);
  await row.getByRole("button", { name: "تعديل" }).click();
  await field(page, "required_role").selectOption({ label: "محاسب" });
  // Wait on both responses the save itself produces (PATCH, then
  // DataTable's refetch) — see 03-non-emergency-approval for why.
  const [saved, refetched] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/api/approval-rules/") && r.request().method() === "PATCH"),
    page.waitForResponse((r) => r.url().includes("/api/approval-rules/") && r.request().method() === "GET"),
    page.getByRole("button", { name: "حفظ التعديلات" }).click(),
  ]);
  expect(saved.ok()).toBeTruthy();
  expect(refetched.ok()).toBeTruthy();
}

async function loginSecondUser(browser: Browser): Promise<Page> {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await page.goto("/login");
  await field(page, "subdomain").fill(SUBDOMAIN);
  await field(page, "email").fill(secondUser.email);
  await field(page, "password").fill(secondUser.password);
  await page.getByRole("button", { name: "تسجيل الدخول" }).click();
  await page.waitForURL("**/dashboard**");
  await expect(page).not.toHaveURL(/\/dashboard\/profile$/); // phase 3 already rotated the temporary password
  return page;
}

async function createApproveAndPost(
  page: Page, approver: Page, slug: "receipts" | "issues", qty: string, unitCost?: string,
) {
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
  const docUrl = new URL(page.url()).pathname;
  await expect(page.getByText("مسودة").first()).toBeVisible();

  // Submit: the active min=0 rule holds it — 202, not auto-approved.
  const submitted = page.waitForResponse((r) => r.url().includes("/submit/") && r.request().method() === "POST");
  await page.getByRole("button", { name: "إرسال للاعتماد" }).click();
  expect((await submitted).status()).toBe(202);
  await expect(page.getByText("بانتظار الاعتماد").first()).toBeVisible();

  // The creator cannot approve their own document.
  const selfApprove = page.waitForResponse((r) => r.url().includes("/approve/") && r.request().method() === "POST");
  await page.getByRole("button", { name: "اعتماد", exact: true }).click();
  expect((await selfApprove).status()).toBe(403);
  await page.reload();
  await expect(page.getByText("بانتظار الاعتماد").first()).toBeVisible();

  // The second user approves — the ordinary path, no emergency dialog.
  await approver.goto(docUrl);
  const approved = approver.waitForResponse((r) => r.url().includes("/approve/") && r.request().method() === "POST");
  await approver.getByRole("button", { name: "اعتماد", exact: true }).click();
  expect((await approved).status()).toBe(200);
  await expect(approver.getByRole("dialog")).toHaveCount(0);
  await expect(approver.getByText("معتمدة").first()).toBeVisible();

  await page.reload();
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

test("7.4: receipt -> approve (second user) -> post -> balance on screen -> issue -> report", async ({ page, browser }) => {
  await requireAccountantOn(page, "إذن إضافة");
  await requireAccountantOn(page, "إذن صرف");
  const approver = await loginSecondUser(browser);

  await createApproveAndPost(page, approver, "receipts", "10", "100");
  let row = await balanceRow(page);
  await expect(row.locator("td").nth(3)).toHaveText("10.00"); // الرصيد
  await expect(row.locator("td").nth(5)).toHaveText("1,000.00"); // القيمة
  await page.screenshot({ path: "../../docs/uat/screens/6.5.8/7.4-balance-after-receipt.png", fullPage: true });

  await createApproveAndPost(page, approver, "issues", "4");
  row = await balanceRow(page);
  await expect(row.locator("td").nth(3)).toHaveText("6.00");
  await expect(row.locator("td").nth(5)).toHaveText("600.00");
  await page.screenshot({ path: "../../docs/uat/screens/6.5.8/7.4-balance-after-issue.png", fullPage: true });

  await approver.context().close();
});
