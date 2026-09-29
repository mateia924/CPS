import { test, expect } from "@playwright/test";
import * as path from "path";

/** Sprint 6.5.15 (UAT item 4): a 400 on a field that's rendered but not
 * currently visible (legal_entity, collapsed inside "متقدم" on the
 * Bank form) must still reach the user — in the general banner,
 * prefixed by the field's own label — instead of only the generic
 * "تعذّر الحفظ." lib/api.ts's generalError() checks this by querying
 * the live DOM, so no per-screen change was needed; this proves it end
 * to end on the exact screen the live bug was reported on. Reuses
 * phase 1's saved Owner session — no real data is touched, the
 * failing response is faked via page.route(). */

const AUTH_DIR = path.join(__dirname, ".auth");

test.use({ storageState: path.join(AUTH_DIR, "state.json") });

function field(page: import("@playwright/test").Page, name: string) {
  return page.locator(`[data-field="${name}"]`).locator("input, select, textarea").first();
}

test("6.5.15 item 4: a 400 on a field hidden inside a collapsed 'متقدم' section shows in the general banner", async ({
  page,
}) => {
  const message = "حساب الخزينة يخص كيانًا قانونيًا مختلفًا";
  await page.route("**/api/banks/", (route) => {
    if (route.request().method() === "POST") {
      return route.fulfill({ status: 400, contentType: "application/json", body: JSON.stringify({ legal_entity: [message] }) });
    }
    return route.continue();
  });

  await page.goto("/dashboard/treasury/banks");
  // The "متقدم" <details> holding legal_entity is deliberately left
  // collapsed — that's the whole point of this scenario. Its own
  // auto-default (me.default_legal_entity_id) still needs to land
  // before submitting, or the native `required` attribute on a still-
  // empty <select> silently blocks the click instead of ever reaching
  // route() — wait for that without ever opening the panel.
  await expect(page.locator("details summary")).toBeVisible();
  await expect(field(page, "legal_entity")).not.toHaveValue("");
  await field(page, "name").fill("بنك اختبار الحقل المخفي");
  await page.getByRole("button", { name: "إضافة", exact: true }).click();

  await expect(page.getByText(`الشركة / الفرع: ${message}`)).toBeVisible();
});
