import { test, expect } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

/** Sprint 8.0 (phase 13): the purchasing settings screen on the tenant
 * phase 1 registered through the UI — so its withholding codes are the
 * ones registration itself seeded, not a fixture's. e2e.sh switches the
 * purchasing module on first (no screen does that yet).
 *
 * The expected codes are read from the same compliance table the loader
 * reads: no rate or code is written here. Every row must carry the
 * "examples — check with your advisor" badge, since nothing has approved
 * them. Then a tolerance is saved and read back after a reload, and the
 * approval-rules screen must name the supplier-bill rule registration
 * seeded (7.5's lesson: a seeded rule the screen cannot name). */

const AUTH_DIR = path.join(__dirname, ".auth");
const SHOTS = "../../docs/uat/screens/6.5.8";
const SA_TABLE: { code: string; name_ar: string; rate: string }[] = JSON.parse(
  fs.readFileSync(path.join(__dirname, "../../backend/apps/compliance/sa/withholding.json"), "utf-8")
);

test.use({ storageState: path.join(AUTH_DIR, "state.json") });

test("8.0: withholding codes carry the examples badge; tolerance saves; supplier-bill rule is named", async ({ page }) => {
  await page.goto("/dashboard/purchasing/settings");
  await expect(page.getByRole("heading", { name: "إعدادات المشتريات" })).toBeVisible();

  const table = page.locator(".card").filter({ hasText: "أكواد ضريبة الاستقطاع" });
  for (const entry of SA_TABLE) {
    const row = table.locator("tbody tr").filter({ hasText: entry.code });
    await expect(row).toHaveCount(1);
    await expect(row).toContainText(entry.name_ar);
    await expect(row).toContainText("أمثلة — راجع استشاريك");
    await expect(row).toContainText(Number(entry.rate).toFixed(2));
  }
  await expect(table.locator("tbody tr")).toHaveCount(SA_TABLE.length);
  // Read-only in 8.0 (the API has no deactivate): no row action, no
  // "show disabled" filter. First walk found both rendered by default.
  await expect(table.getByRole("button", { name: "تعطيل" })).toHaveCount(0);
  await expect(table.getByText("إظهار المعطل")).toHaveCount(0);
  await page.screenshot({ path: `${SHOTS}/8.0-withholding-codes-examples.png`, fullPage: true });

  const pct = page.locator('[data-field="match_tolerance_pct"] input');
  await expect(pct).toHaveValue("2.00");
  const saved = page.waitForResponse((r) => r.url().includes("/purchasing/settings/") && r.request().method() === "PATCH");
  await pct.fill("3.5");
  await pct.blur();
  expect((await saved).status()).toBe(200);
  await page.reload();
  await expect(page.locator('[data-field="match_tolerance_pct"] input')).toHaveValue("3.50");

  await page.goto("/dashboard/settings/approval-rules");
  await expect(page.getByRole("cell", { name: "فاتورة مورد" })).toBeVisible();
});
