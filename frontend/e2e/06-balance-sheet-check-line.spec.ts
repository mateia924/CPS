import { test, expect } from "@playwright/test";
import * as path from "path";

/** Sprint 6.5.17 (UAT item 3, "لم يُنفَّذ في 6.5.15 رغم النص"): the
 * balance sheet screen must show an explicit "الأصول = الخصوم + حقوق
 * الملكية" check line with a balanced/unbalanced verdict, not just
 * balanced totals with no stated identity. Reuses phase 1's saved
 * Owner session and its own real postings (voucher on FIXED_ASSETS,
 * asset depreciation) — a real, live-computed check, not a mock. */

const AUTH_DIR = path.join(__dirname, ".auth");

test.use({ storageState: path.join(AUTH_DIR, "state.json") });

test("6.5.17 item 3: the balance sheet page shows the balanced check line", async ({ page }) => {
  await page.goto("/dashboard/reports/balance-sheet");
  await expect(page.getByText("الأصول = الخصوم + حقوق الملكية")).toBeVisible();
  await expect(page.getByText("الأصول = الخصوم + حقوق الملكية — متوازن")).toBeVisible();
});
