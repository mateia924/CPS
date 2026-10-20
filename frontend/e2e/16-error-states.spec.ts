import { test, expect, Page, Route } from "@playwright/test";
import * as path from "path";

/** Block 8.0.2: every failure a screen does not handle itself gets a named
 * state — and a list never renders a failure as an empty result. The 8.0.1
 * walk found an API 404 and a JSON 500 leaving a blank main area, and an
 * HTML 500 on a list showing «لا توجد بيانات لعرضها».
 *
 * The 404 is the real server's (a bill id that does not exist). The 500s
 * are forced in the browser by answering the API call with a 500 — a JSON
 * body, and Django's bare HTML page — since nothing on a healthy dev stack
 * fails on demand. Run by scripts/e2e_access.sh (an Owner on a fresh
 * smoke-* tenant with purchasing on). */

const SUBDOMAIN = process.env.E2E_SUBDOMAIN!;
const EMAIL = process.env.E2E_OWNER_EMAIL!;
const PASSWORD = process.env.E2E_OWNER_PASSWORD!;
const SHOTS = path.join(__dirname, "../../docs/uat/screens/8.0.2");
const NO_DATA = "لا توجد بيانات لعرضها";

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

const html500 = (route: Route) =>
  route.fulfill({ status: 500, contentType: "text/html", body: "<h1>Server Error (500)</h1>" });
const json500 = (route: Route) =>
  route.fulfill({ status: 500, contentType: "application/json", body: '{"detail": "boom"}' });

test.beforeAll(() => {
  expect(SUBDOMAIN && EMAIL && PASSWORD, "run through scripts/e2e_access.sh").toBeTruthy();
});

test("API 404 renders a named not-found state", async ({ page }) => {
  await login(page);
  const missing = page.waitForResponse((r) => r.url().includes("/api/purchasing/bills/00000000-"));
  await page.goto("/dashboard/purchasing/bills/00000000-0000-0000-0000-000000000000");
  expect((await missing).status()).toBe(404);
  await expect(page.locator('main [data-state="not-found"]')).toBeVisible();
  await expect(page.locator("main")).toContainText("غير موجود");
  await page.screenshot({ path: `${SHOTS}/01-api-404-missing-bill.png`, fullPage: true });

  // An unknown route: the app's own not-found, not Next's English default.
  await page.goto("/dashboard/no-such-screen");
  await expect(page.locator('[data-state="not-found"]')).toBeVisible();
  await expect(page.getByText("This page could not be found")).toHaveCount(0);
  await page.screenshot({ path: `${SHOTS}/02-unknown-route.png`, fullPage: true });
});

test("JSON 500 renders a named server-error state", async ({ page }) => {
  await login(page);
  await page.route("**/api/purchasing/settings/", json500);
  await page.goto("/dashboard/purchasing/settings");
  await expect(page.locator('main [data-state="server-error"]')).toBeVisible();
  await expect(page.locator("main")).toContainText("خطأ في الخادم");
  await page.screenshot({ path: `${SHOTS}/03-json-500-purchasing-settings.png`, fullPage: true });
});

test("HTML 500 on a list renders server-error, never no-data", async ({ page }) => {
  await login(page);
  const lists: [string, string, string][] = [
    ["/dashboard/purchasing/bills", "**/api/purchasing/bills/?**", "04-html-500-bills-list"],
    ["/dashboard/purchasing/expenses", "**/api/purchasing/expenses/?**", "05-html-500-expenses-list"],
    ["/dashboard/products", "**/api/products/?**", "06-html-500-items-list"],
  ];
  for (const [url, api, shot] of lists) {
    await page.route(api, html500);
    await page.goto(url);
    const table = page.locator("table").last();
    // Wait for the failed request to land, then: never read as empty, and say so.
    await page.waitForLoadState("networkidle");
    await expect(table, `${url}: a failed list must never read as empty`).not.toContainText(NO_DATA);
    await expect(table.locator('[data-state="server-error"]'), `${url}: the failed list must say so`).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/${shot}.png`, fullPage: true });
    await page.unroute(api);
  }
  // Not a DataTable: the approvals inbox builds its own list. A failed
  // load must not tell an approver that nothing is waiting.
  await page.route("**/api/approvals/pending/", html500);
  await page.goto("/dashboard/approvals");
  await page.waitForLoadState("networkidle");
  await expect(page.locator("main")).not.toContainText("لا توجد مستندات بانتظار اعتمادك");
  await expect(page.locator('main [data-state="server-error"]').first()).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/07-html-500-approval-inbox.png`, fullPage: true });
  await page.unroute("**/api/approvals/pending/");

  // The same list, healthy again, still shows a real empty state.
  await page.goto("/dashboard/purchasing/bills");
  await expect(page.locator("table").last()).toContainText(NO_DATA);
});

test("side lists show a failure, never an empty list", async ({ page }) => {
  await login(page);

  // Sessions on the profile screen: the failure used to be swallowed and
  // read «لا جلسات نشطة أخرى».
  await page.route("**/api/auth/sessions/", html500);
  await page.goto("/dashboard/profile");
  await page.waitForLoadState("networkidle");
  await expect(page.locator("main")).not.toContainText("لا جلسات نشطة أخرى");
  await expect(page.locator('main [data-state="server-error"]').first()).toBeVisible();
  await page.unroute("**/api/auth/sessions/");

  // Attachments (company settings): not «لا مرفقات بعد», and the badge
  // shows «!» instead of a count of zero.
  await page.route("**/api/attachments/?**", html500);
  await page.goto("/dashboard/settings/company");
  await page.waitForLoadState("networkidle");
  const badge = page.getByRole("button", { name: /المرفقات/ }).first();
  await expect(badge).toContainText("(!)");
  await badge.click();
  await expect(page.locator("main")).not.toContainText("لا مرفقات بعد");
  await expect(page.locator('main [data-state="server-error"]').first()).toBeVisible();
  await page.unroute("**/api/attachments/?**");

  // Change history on a product: not «لا سجل تغييرات بعد».
  const productId = await page.evaluate(async () => {
    const res = await fetch(`${window.location.origin}/api/products/`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${localStorage.getItem("cps_access")}` },
      body: JSON.stringify({ sku: "E2E-ERR-1", name: "صنف اختبار الأخطاء", unit_price: "10.00", item_type: "service" }),
    });
    if (res.status !== 201) throw new Error(`product create: ${res.status} ${await res.text()}`);
    return (await res.json()).id as string;
  });
  await page.route("**/api/audit-log/?**", html500);
  await page.goto(`/dashboard/products/${productId}`);
  await page.waitForLoadState("networkidle");
  await page.getByRole("heading", { name: /سجل التغييرات/ }).click();
  await expect(page.locator("main")).not.toContainText("لا سجل تغييرات بعد");
  await expect(page.locator('main [data-state="server-error"]').first()).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/08-html-500-change-history.png`, fullPage: true });
});
