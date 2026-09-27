import { test, expect, type Page } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

/** Sprint 6.5.8: part 2 — resumes the browser session part 1 saved
 * (same logged-in Owner), now that the `e2e` Makefile target has
 * seeded a second (Accountant) user on the tenant between the two
 * files, via create_test_user (see 01-setup-and-schedule.spec.ts's own
 * header comment for why that's a management command and not a UI
 * flow). Exercises item 4 (the approve button's emergency-reason
 * prompt) and the "توليد المستحق الآن" button (sprint 6.5.7). */

const SCREENSHOTS_DIR = path.join(__dirname, "../../docs/uat/screens/6.5.8");
const AUTH_DIR = path.join(__dirname, ".auth");
const context = JSON.parse(fs.readFileSync(path.join(AUTH_DIR, "context.json"), "utf-8"));

test.use({ storageState: path.join(AUTH_DIR, "state.json") });

let shotIndex = 20; // continues numbering after part 1's screenshots
async function shot(page: Page, name: string) {
  shotIndex += 1;
  await page.screenshot({
    path: path.join(SCREENSHOTS_DIR, `${String(shotIndex).padStart(2, "0")}-${name}.png`),
    fullPage: true,
  });
}

test("6.5.8 UAT part 2: emergency-approval prompt, generate due now", async ({ page }) => {
  await page.goto(`/dashboard/assets/${context.assetId}`);
  await expect(page.getByText("بانتظار الاعتماد").first()).toBeVisible();
  await shot(page, "resumed-pending-approval");

  await test.step("item 4: approve prompts for an emergency reason when needed, then succeeds", async () => {
    let promptSeen = "";
    page.once("dialog", async (dialog) => {
      promptSeen = dialog.message();
      await dialog.accept("لا محاسب آخر نشط متاح لاعتماد هذا الجدول");
    });
    await page.getByRole("button", { name: "اعتماد", exact: true }).click();
    await expect.poll(() => promptSeen).not.toBe("");
    await expect(page.getByText("معتمدة").first()).toBeVisible();
    await shot(page, "approved-via-emergency-reason");

    // item 5: now that it's approved, the real remaining-months count
    // replaces the "—" placeholder from part 1.
    const remainingCard = page.locator(".card", { hasText: "الأشهر المتبقية" }).last();
    await expect(remainingCard).not.toContainText("—");
  });

  await test.step("sprint 6.5.7: generate due now, scoped to this asset's schedule", async () => {
    await page.getByRole("button", { name: "توليد المستحق الآن" }).click();
    const banner = page.getByTestId("warnings-banner-warning");
    await expect(banner).toContainText("تم توليد");
    await shot(page, "generate-due-now-result");
  });
});
