import { test, expect } from "@playwright/test";
import * as path from "path";

/** Sprint 6.6.6 (B-list item 11): a document still reaches the
 * inbox because the user's own role matches the rule, but approving
 * it would 403 if they created it themselves (no single-active-user
 * exemption) — apps.approvals.services.list_pending_approvals now
 * says so per row (`can_approve`), and the inbox must hide its own
 * Approve button instead of letting the user find out by clicking
 * it. Reuses phase 1's saved Owner session; the inbox response is
 * faked via page.route() — no real multi-owner tenant state needed. */

const AUTH_DIR = path.join(__dirname, ".auth");

test.use({ storageState: path.join(AUTH_DIR, "state.json") });

test("6.6.6 item 11: Approve is hidden for a row this user created themselves", async ({ page }) => {
  const ownRow = {
    doc_type: "journal_entry",
    id: "22222222-2222-2222-2222-222222222222",
    number: "JV-2026-00099",
    date: "2026-09-26",
    description: "قيد اختبار أنشأه المستخدم نفسه",
    amount_base: "500.00",
    created_by: "self",
    can_approve: false,
  };

  await page.route("**/api/approvals/pending/", (route) =>
    route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({ results: [ownRow], blocked: { count: 0, role_names: [] } }),
    })
  );

  await page.goto("/dashboard/approvals");
  await expect(page.getByText("JV-2026-00099")).toBeVisible();
  await expect(page.getByText("لا يمكنك اعتماد مستند أنشأته أنت")).toBeVisible();
  await expect(page.getByRole("button", { name: "اعتماد", exact: true })).not.toBeVisible();
  // "رفض بسبب" is unaffected — only the Approve button hides.
  await expect(page.getByRole("button", { name: "رفض بسبب", exact: true })).toBeVisible();
});
