import { test, expect } from "@playwright/test";
import * as path from "path";

/** Sprint 6.5.18 (UAT item 6): a 6.5.10-era regression in lib/api.ts's
 * generalError() only ever read `detail` when DRF sent it as a plain
 * string — apps.vouchers.services._balance_warnings_and_checks raises
 * `{"detail": [message]}` (a *list*, DRF's own shape for a service-
 * raised ValidationError), so the message was silently swallowed down
 * to the generic "تعذّر الحفظ." fallback on every screen, not just this
 * one. Reuses phase 1's saved Owner session; the voucher list and the
 * failing post/ call are both faked via page.route() — no real
 * insufficient-balance state needs to exist on the smoke tenant. */

const AUTH_DIR = path.join(__dirname, ".auth");

test.use({ storageState: path.join(AUTH_DIR, "state.json") });

test("6.5.18 item 6: array-shaped detail on a failed voucher post shows verbatim, not the generic fallback", async ({
  page,
}) => {
  const message = "رصيد حساب الخزينة هذا لا يكفي لهذا السند: الرصيد 0.00، والعجز 500.00.";
  const fakeVoucher = {
    id: "11111111-1111-1111-1111-111111111111",
    number: "PV-2026-00099",
    date: "2026-09-26",
    party_name: null,
    payee_name: "مورد اختبار",
    treasury_name: "صندوق اختبار",
    total_fc: "500.00",
    currency: "SAR",
    status: "draft",
  };

  await page.route("**/api/vouchers/**", (route) => {
    const request = route.request();
    if (request.method() === "GET") {
      return route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify({ count: 1, next: null, previous: null, results: [fakeVoucher] }),
      });
    }
    if (request.method() === "POST" && request.url().endsWith("/post/")) {
      return route.fulfill({ status: 400, contentType: "application/json", body: JSON.stringify({ detail: [message] }) });
    }
    return route.continue();
  });

  // Sprint 6.5.18: dismiss the native alert() first — asserting
  // inside the handler before dismissing races the test's own
  // teardown (the assertion's rejection surfaces as a confusing
  // "Target page ... has been closed" instead of the real mismatch).
  let dialogMessage: string | null = null;
  page.once("dialog", async (dialog) => {
    dialogMessage = dialog.message();
    await dialog.dismiss();
  });

  await page.goto("/dashboard/treasury/vouchers/payment");
  await expect(page.getByText("PV-2026-00099")).toBeVisible();
  // 2026-10-05: wait on the posting request's own (mocked) response
  // first — the 400 itself — before the dialog text. expect.poll()
  // below was already signal-based (polling a variable an event
  // listener sets, not a sleep), but it gave no visibility into
  // WHETHER the request that's supposed to produce that dialog had
  // even completed; this makes that explicit, per the project's own
  // "wait for the signal, not a deadline" rule for e2e.
  const [postResponse] = await Promise.all([
    page.waitForResponse((res) => res.url().endsWith("/post/") && res.request().method() === "POST"),
    page.getByRole("button", { name: "ترحيل", exact: true }).click(),
  ]);
  expect(postResponse.status()).toBe(400);
  await expect.poll(() => dialogMessage).toBe(message);
});
