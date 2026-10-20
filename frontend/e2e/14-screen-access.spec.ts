import { test, expect, Page } from "@playwright/test";

/** Block 8.0.1: the two defects 8.0's live browser walk found, as a role
 * that lacks purchasing.view (Viewer) on a tenant with the purchasing
 * module on — scripts/e2e_access.sh builds that tenant and user.
 *
 * 1. The sidebar rendered a link to purchasing settings the Viewer could
 *    not open. Now every entry carries its permission (lib/nav.ts). The
 *    suppliers link must still show (the Viewer holds parties.view): the
 *    section is there, only the one entry is gated. Then every link the
 *    Viewer does see is opened, and none may land on the no-permission
 *    state.
 * 2. Opening the screen anyway gave a blank main area. Now the shell
 *    names the reason (components/ScreenAccess.tsx). */

const SUBDOMAIN = process.env.E2E_SUBDOMAIN!;
const EMAIL = process.env.E2E_VIEWER_EMAIL!;
const PASSWORD = process.env.E2E_VIEWER_PASSWORD!;
const SHOTS = "../../docs/uat/screens/6.5.8";

function field(page: Page, name: string) {
  return page.locator(`[data-field="${name}"]`).locator("input, select, textarea").first();
}

async function login(page: Page) {
  await page.goto("/login");
  await field(page, "subdomain").fill(SUBDOMAIN);
  await field(page, "email").fill(EMAIL);
  await field(page, "password").fill(PASSWORD);
  await page.getByRole("button", { name: "تسجيل الدخول" }).click();
  await page.waitForURL("**/dashboard");
}

test.beforeAll(() => {
  expect(SUBDOMAIN && EMAIL && PASSWORD, "run through scripts/e2e_access.sh").toBeTruthy();
});

test("sidebar shows no link the user cannot open", async ({ page }) => {
  await login(page);
  const sidebar = page.locator("aside.sidebar");
  await expect(sidebar.locator('a[href="/dashboard/suppliers"]')).toBeVisible();
  await expect(sidebar.locator('a[href="/dashboard/purchasing/settings"]')).toHaveCount(0);

  const hrefs = await sidebar.locator("a[href]").evaluateAll((links) => links.map((a) => a.getAttribute("href")!));
  expect(hrefs.length).toBeGreaterThan(3);
  for (const href of hrefs) {
    await page.goto(href);
    await page.waitForLoadState("networkidle");
    await expect.soft(page.locator('[data-state="forbidden"]'), `${href} is linked but refused`).toHaveCount(0);
  }
});

test("a refused screen names the reason instead of rendering blank", async ({ page }) => {
  await login(page);
  const refused = page.waitForResponse((r) => r.url().includes("/purchasing/settings/") && r.request().method() === "GET");
  await page.goto("/dashboard/purchasing/settings");
  expect((await refused).status()).toBe(403);
  const state = page.locator('main [data-state="forbidden"]');
  await expect(state).toBeVisible();
  await expect(state.getByRole("heading", { name: "ليس لديك صلاحية" })).toBeVisible();
  await expect(page.locator("main")).not.toHaveText("");
  await page.screenshot({ path: `${SHOTS}/8.0.1-purchasing-settings-forbidden.png`, fullPage: true });
});
