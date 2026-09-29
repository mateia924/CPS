import { test, expect, type Page } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

/** Sprint 6.5.10 (owner verification, item 6): the whole rest of this
 * suite so far only ever exercises the *emergency* approval override
 * (creator blocked, no other role-holder exists). This proves the
 * ordinary path actually works too — a second, real user created
 * through the "مستخدم جديد" screen (not create_test_user, which exists
 * only to seed the emergency scenario's second user), given the
 * Accountant role on the asset_depreciation approval rule through the
 * settings picker (sprint 6.5.9's own fix), logging in for themselves
 * in a fresh browser context, and approving a schedule they didn't
 * create — no emergency dialog should appear at all. */

const SCREENSHOTS_DIR = path.join(__dirname, "../../docs/uat/screens/6.5.8");
const AUTH_DIR = path.join(__dirname, ".auth");
const context = JSON.parse(fs.readFileSync(path.join(AUTH_DIR, "context.json"), "utf-8"));
const SUBDOMAIN: string = context.subdomain;

test.use({ storageState: path.join(AUTH_DIR, "state.json") });

let shotIndex = 30;
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

test("6.5.10 item 6: genuine creator != approver, a real second user made through the UI", async ({
  page,
  browser,
}) => {
  const accountantEmail = `accountant2-${Date.now()}@${SUBDOMAIN}.test`;
  const accountantPassword = "AccountantUI!2026";

  await test.step("create a second user (Accountant) via الأدوار والمستخدمون ← مستخدم جديد", async () => {
    await page.goto("/dashboard/roles");
    await page.getByRole("button", { name: "مستخدم جديد" }).click();
    await field(page, "first_name").fill("محاسب");
    await field(page, "last_name").fill("ثانٍ");
    await field(page, "email").fill(accountantEmail);
    await field(page, "password").fill(accountantPassword);
    await page.getByRole("checkbox", { name: "محاسب" }).check();
    await page.getByRole("button", { name: "إضافة", exact: true }).click();
    await expect(page.getByText(accountantEmail).first()).toBeVisible();
    await shot(page, "second-user-created-via-ui");
  });

  await test.step("edit the asset_depreciation approval rule to require Accountant, via the picker fixed in 6.5.9", async () => {
    await page.goto("/dashboard/settings/approval-rules");
    const row = page.locator("tr", { hasText: "جدول إهلاك أصل" });
    await row.getByRole("button", { name: "تعديل" }).click();
    await field(page, "required_role").selectOption({ label: "محاسب" });
    await page.getByRole("button", { name: "حفظ التعديلات" }).click();
    await shot(page, "approval-rule-now-requires-accountant");

    // The list view has no required_role column (doc_type/min_amount
    // only) — re-open edit mode to confirm the saved value directly,
    // a real check instead of trusting the save silently worked.
    await row.getByRole("button", { name: "تعديل" }).click();
    const accountantRoleId = await field(page, "required_role")
      .locator('option:has-text("محاسب")')
      .getAttribute("value");
    await expect(field(page, "required_role")).toHaveValue(accountantRoleId!);
    await page.getByRole("button", { name: "إلغاء" }).click();
  });

  const newAssetId = await test.step("create a second depreciable asset and start its schedule", async () => {
    await page.goto("/dashboard/assets");
    await field(page, "code").fill("AST-E2E-2");
    await field(page, "name").fill("أصل اختبار E2E الثاني");
    await field(page, "purchase_date").fill("2026-08-01");
    await field(page, "purchase_cost").fill("6000");
    await field(page, "useful_life_months").fill("12");
    // Sprint 6.5.12 discovery: /auth/me/'s legal_entity_ids is sorted
    // alphabetically by UUID (apps/accounts/views.py MeView), not by
    // entity_type — the asset form's auto-default (legal_entity_ids[0])
    // can land on the tenant's COMPANY row instead of its BRANCH, while
    // a new simplified-mode user (CreateUserSerializer) always gets the
    // BRANCH specifically (default_branch_for_tenant). A real, separate
    // product bug (registered, not fixed here) — worked around here by
    // picking the branch explicitly via the always-available "متقدم"
    // section (unlike the voucher screens, this one isn't hidden in
    // simplified mode), matching what an accountant would sensibly do
    // by hand once they noticed the same mismatch.
    await page.getByText("متقدم").click();
    const branchValue = await field(page, "legal_entity")
      .locator('option:has-text("الفرع الرئيسي")')
      .getAttribute("value");
    await field(page, "legal_entity").selectOption(branchValue!);
    await page.getByRole("button", { name: "إضافة", exact: true }).click();
    await expect(page.getByText("AST-E2E-2").first()).toBeVisible();

    const row = page.locator("tr", { hasText: "AST-E2E-2" });
    await row.getByRole("link", { name: "عرض التفاصيل" }).click();
    await page.waitForURL("**/dashboard/assets/*");
    const id = page.url().split("/").filter(Boolean).pop()!;

    await page.getByRole("button", { name: "بدء الإهلاك" }).click();
    await expect(page.getByText("بانتظار الاعتماد").first()).toBeVisible();
    await shot(page, "second-schedule-pending-accountant-required");
    return id;
  });

  await test.step("log in as the Accountant in a fresh browser context and approve — no emergency dialog", async () => {
    const accountantContext = await browser.newContext();
    const accountantPage = await accountantContext.newPage();
    await accountantPage.goto("/login");
    await field(accountantPage, "subdomain").fill(SUBDOMAIN);
    await field(accountantPage, "email").fill(accountantEmail);
    await field(accountantPage, "password").fill(accountantPassword);
    await accountantPage.getByRole("button", { name: "تسجيل الدخول" }).click();
    await accountantPage.waitForURL("**/dashboard**");

    await accountantPage.goto(`/dashboard/assets/${newAssetId}`);
    await accountantPage.getByRole("button", { name: "اعتماد", exact: true }).click();
    // The real, non-emergency path: no reason dialog should appear at
    // all, since this user genuinely holds the required role and
    // didn't create the schedule.
    await expect(accountantPage.getByRole("dialog")).toHaveCount(0);
    await expect(accountantPage.getByText("معتمدة").first()).toBeVisible();
    await shot(accountantPage, "real-approval-by-accountant-not-emergency");
    await accountantContext.close();
  });
});
