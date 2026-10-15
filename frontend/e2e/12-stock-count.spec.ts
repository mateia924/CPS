import { test, expect, type Browser, type Page } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

/** Sprint 7.5 follow-up (phase 12): a count session walked on the screens,
 * through the real approval path — the stock_count rule registration
 * seeds (min=0 -> Owner), re-pointed to Accountant on the approval-rules
 * screen exactly like phase 11 does for receipts and issues.
 *
 * Before: phase 11 left E2E-STK-1 at 6 x 100 = 600.00 in E2E-W1; this spec
 * first receives E2E-SER-1 (serial-tracked, seeded by e2e.sh) — 3 serials
 * at 500 — over HTTP, with the second user approving. Then, on the screens:
 * open a session -> the find-item box refuses a serial not in the warehouse
 * by name -> count E2E-STK-1 = 8 (surplus +2) and scan 2 of the 3 serials
 * (shortage 1) -> enter a surplus unit cost of 70 -> submit (202) -> the
 * second user approves -> post. The numbers are then read back over HTTP:
 *
 *   surplus  +2 x 70  = 140.00  Dr 1400 / Cr 5070
 *   shortage -1 x 500 = 500.00  Dr 5070 / Cr 1400
 *   1400 = 600 + 1500 + 140 - 500 = 1740.00;  5070 = 500 - 140 = 360.00
 *
 * The second test reverses the session on the screen. e2e.sh checks the
 * serial statuses and the reconciliation invariant (Σ inventory accounts ==
 * Σ ItemCost.total_value == Σ StockMove.value) in the database after each
 * test — neither is exposed over HTTP. */

const AUTH_DIR = path.join(__dirname, ".auth");
const SHOTS = "../../docs/uat/screens/6.5.8";
const context = JSON.parse(fs.readFileSync(path.join(AUTH_DIR, "context.json"), "utf-8"));
const SUBDOMAIN: string = context.subdomain;
const secondUser: { email: string; password: string } = JSON.parse(
  fs.readFileSync(path.join(AUTH_DIR, "second-user.json"), "utf-8")
);
const SESSION_FILE = path.join(AUTH_DIR, "count-session.json");

test.use({ storageState: path.join(AUTH_DIR, "state.json") });

function field(page: Page, name: string) {
  return page.locator(`[data-field="${name}"]`).locator("input, select, textarea").first();
}

/** Layout, not just text: every cell of the variances table sits under its
 * own column header. A display:inline-block <td> once pushed figures under
 * the wrong headings while the DOM order — and every text assertion —
 * stayed right. Run on each state the tab has: a draft (with «الرصيد الآن»,
 * where it was seen), posted, and reversed (without it). */
async function expectCellsUnderTheirHeaders(page: Page) {
  const misaligned = await page.getByTestId("count-variances").evaluate((card) => {
    const heads = [...card.querySelectorAll("thead th")].map((th) => ({ text: th.textContent, box: th.getBoundingClientRect() }));
    const bad: string[] = [];
    card.querySelectorAll("tbody tr").forEach((tr, r) => {
      [...tr.children].forEach((td, i) => {
        const b = td.getBoundingClientRect();
        const h = heads[i];
        if (!h || Math.abs(b.left - h.box.left) > 1 || Math.abs(b.right - h.box.right) > 1) {
          bad.push(`row ${r} cell ${i} «${td.textContent?.trim()}» not under «${h?.text ?? "—"}»`);
        }
      });
    });
    return bad;
  });
  expect(misaligned).toEqual([]);
}

/** The app's own API, from inside the page — same origin, same token
 * (refreshed once on a 401, the way lib/api.ts does it). */
async function api(page: Page, method: string, apiPath: string, body?: unknown) {
  return page.evaluate(
    async ({ method, apiPath, body }) => {
      const call = () =>
        fetch(`/api${apiPath}`, {
          method,
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${window.localStorage.getItem("cps_access")}`,
          },
          body: body === undefined ? undefined : JSON.stringify(body),
        });
      let res = await call();
      if (res.status === 401) {
        const refreshed = await fetch("/api/auth/refresh/", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh: window.localStorage.getItem("cps_refresh") }),
        });
        window.localStorage.setItem("cps_access", (await refreshed.json()).access);
        res = await call();
      }
      const text = await res.text();
      return { status: res.status, body: text ? JSON.parse(text) : null };
    },
    { method, apiPath, body }
  );
}

function rowsOf(body: unknown): Record<string, string>[] {
  return Array.isArray(body) ? body : (body as { results: Record<string, string>[] }).results;
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
  return page;
}

async function trialBalance(page: Page) {
  const tb = await api(page, "GET", "/journal-entries/trial_balance/");
  expect(tb.status).toBe(200);
  const byCode = Object.fromEntries(
    (tb.body.rows as { account_code: string; debit: string; credit: string; balance: string }[]).map((r) => [r.account_code, r])
  );
  return { byCode, totalDebit: tb.body.total_debit as string, totalCredit: tb.body.total_credit as string };
}

async function stockLevel(page: Page, sku: string) {
  const res = await api(page, "GET", `/stock-levels/?search=${sku}`);
  expect(res.status).toBe(200);
  const matches = rowsOf(res.body).filter((r) => r.item_sku === sku);
  expect(matches).toHaveLength(1); // one warehouse on the smoke tenant
  const row = matches[0];
  return { qty: row.qty_on_hand, avg: row.avg_cost, value: row.value };
}

test("7.5: count session — shortage + surplus at an entered cost, approved, posted, trial balance", async ({ page, browser }) => {
  // The stock_count rule registration seeded — re-pointed on the screen.
  await page.goto("/dashboard/settings/approval-rules");
  const ruleRow = page.locator("tr", { hasText: "جلسة جرد" });
  await expect(ruleRow).toHaveCount(1); // the seeded row, named (it had no label before this block)
  await ruleRow.getByRole("button", { name: "تعديل" }).click();
  await field(page, "required_role").selectOption({ label: "محاسب" });
  const [saved] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/api/approval-rules/") && r.request().method() === "PATCH"),
    page.waitForResponse((r) => r.url().includes("/api/approval-rules/") && r.request().method() === "GET"),
    page.getByRole("button", { name: "حفظ التعديلات" }).click(),
  ]);
  expect(saved.ok()).toBeTruthy();

  const approver = await loginSecondUser(browser);

  // --- before: E2E-SER-1 received with 3 serials at 500, over HTTP.
  const entity = rowsOf((await api(page, "GET", "/legal-entities/")).body).find((e) => e.code === "MAIN-01")!;
  const warehouse = rowsOf((await api(page, "GET", "/warehouses/?search=E2E-W1")).body).find((w) => w.code === "E2E-W1")!;
  const serialItem = rowsOf((await api(page, "GET", "/products/?search=E2E-SER-1")).body).find((p) => p.sku === "E2E-SER-1")!;
  const today = new Date().toISOString().slice(0, 10);
  const receipt = await api(page, "POST", "/stock-documents/", {
    kind: "receipt", legal_entity: entity.id, warehouse: warehouse.id, date: today,
    lines: [{ item: serialItem.id, qty: "3", unit_cost: "500", serials: ["E2E-SN-1", "E2E-SN-2", "E2E-SN-3"] }],
  });
  expect(receipt.status, JSON.stringify(receipt.body)).toBe(201);
  expect((await api(page, "POST", `/stock-documents/${receipt.body.id}/submit/`)).status).toBe(202);
  expect((await api(approver, "POST", `/stock-documents/${receipt.body.id}/approve/`, {})).status).toBe(200);
  expect((await api(page, "POST", `/stock-documents/${receipt.body.id}/post/`, {})).status).toBe(200);

  let tb = await trialBalance(page);
  expect(tb.byCode["1400"].balance).toBe("2100.00"); // 600 (phase 11) + 1500

  // --- open the session on the screen.
  await page.goto("/dashboard/inventory/stock/counts");
  await page.waitForLoadState("networkidle");
  const entitySelect = field(page, "legal_entity");
  await entitySelect.selectOption(entity.id);
  await field(page, "warehouse").selectOption({ label: "E2E-W1 — مستودع e2e" });
  await page.getByRole("button", { name: "فتح جلسة جرد" }).click();
  await page.waitForURL(/\/dashboard\/inventory\/stock\/[0-9a-f-]{36}$/);
  const sessionUrl = new URL(page.url()).pathname;
  const sessionId = sessionUrl.split("/").pop()!;
  fs.writeFileSync(SESSION_FILE, JSON.stringify({ sessionUrl, sessionId }));
  await expect(page.getByText("مسودة").first()).toBeVisible();

  // The find-item box: a serial that isn't in the warehouse is refused by name.
  await field(page, "find_item").fill("E2E-SN-404");
  const refused = page.waitForResponse((r) => r.url().includes("/find-item/"));
  await page.getByRole("button", { name: "حاول الإضافة" }).click();
  expect((await refused).status()).toBe(400);
  await expect(page.getByText(/E2E-SN-404.*غير مسجَّل في هذا المستودع — أدخله بإذن إضافة من «أذون الإضافة» ثم أعد العدّ/)).toBeVisible();
  // ... and an item already on the sheet is pointed to, not added.
  await field(page, "find_item").fill("E2E-STK-1");
  const pointed = page.waitForResponse((r) => r.url().includes("/find-item/"));
  await page.getByRole("button", { name: "حاول الإضافة" }).click();
  expect((await pointed).status()).toBe(200);
  await expect(page.getByText(/في الجلسة — أدخل عدّه في سطره/)).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/7.5f-find-item.png`, fullPage: true });

  // Count: E2E-STK-1 = 8 (surplus +2), E2E-SER-1 = 2 of 3 serials scanned (shortage 1).
  await page.locator("tr", { hasText: "E2E-STK-1" }).locator("input").first().fill("8");
  await page.locator("tr", { hasText: "E2E-SER-1" }).locator("textarea").fill("E2E-SN-1\nE2E-SN-2");
  const counted = page.waitForResponse((r) => r.url().includes("/counts/") && r.request().method() === "POST");
  await page.getByRole("button", { name: "حفظ العدّ" }).click();
  expect((await counted).status()).toBe(200);
  await expect(page.getByText("حُفظ العدّ.")).toBeVisible();

  // Variances: the surplus unit cost, entered and saved.
  await page.getByRole("button", { name: "الفروق", exact: true }).click();
  const surplusRow = page.getByTestId("count-variances").locator("tr", { hasText: "E2E-STK-1" });
  await surplusRow.locator("input").fill("70");
  const costSaved = page.waitForResponse((r) => r.url().includes("/surplus-costs/"));
  await page.getByRole("button", { name: "حفظ تكاليف الزيادة" }).click();
  expect((await costSaved).status()).toBe(200);
  await page.getByRole("button", { name: "الفروق", exact: true }).click();
  await expect(page.getByTestId("count-variances").locator("tr", { hasText: "E2E-STK-1" })).toContainText("140.00");
  await expect(page.getByTestId("count-variances").locator("tr", { hasText: "E2E-SER-1" })).toContainText("−500.00");
  // The change history names the change.
  await page.getByRole("heading", { name: /سجل التغييرات/ }).click();
  await expect(page.getByText(/E2E-STK-1 — .*: بالمتوسط → 70\.00/)).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/7.5f-variances-surplus-cost.png`, fullPage: true });
  await expectCellsUnderTheirHeaders(page);

  // The printed count sheet: the entered cost is printed, and the sheet ends
  // with the empty «أصناف وُجدت وليست في الورقة» section to write in.
  const sheet = await page.context().newPage();
  await sheet.goto(`${new URL(page.url()).origin}/print/stock/count/${sessionUrl.split("/").pop()}`);
  await expect(sheet.getByTestId("count-sheet").locator("tr", { hasText: "E2E-STK-1" })).toContainText("70.00");
  const extras = sheet.getByTestId("count-sheet-extras");
  await expect(extras.getByRole("heading", { name: "أصناف وُجدت وليست في الورقة" })).toBeVisible();
  await expect(extras.locator("thead th")).toHaveText(["#", "الوصف", "الكمية", "الموقع"]);
  expect(await extras.locator("tbody tr").count()).toBeGreaterThan(0);
  await expect(extras.locator("tbody td:not(:first-child)").filter({ hasText: /\S/ })).toHaveCount(0);
  await sheet.screenshot({ path: `${SHOTS}/7.5f-count-sheet-print.png`, fullPage: true });
  await sheet.close();

  // Submit -> held by the re-pointed rule; the second user approves; the Owner posts.
  const submitted = page.waitForResponse((r) => r.url().includes("/submit/") && r.request().method() === "POST");
  await page.getByRole("button", { name: "إرسال للاعتماد" }).click();
  expect((await submitted).status()).toBe(202);
  await expect(page.getByText("بانتظار الاعتماد").first()).toBeVisible();

  await approver.goto(sessionUrl);
  const approved = approver.waitForResponse((r) => r.url().includes("/approve/") && r.request().method() === "POST");
  await approver.getByRole("button", { name: "اعتماد", exact: true }).click();
  expect((await approved).status()).toBe(200);
  await expect(approver.getByText("معتمدة").first()).toBeVisible();

  // The approver approved an amount. Changing the surplus cost on the
  // approved session changes it: the session goes back to draft with its
  // counts kept, cannot be posted, and needs a new approval.
  await page.reload();
  await expect(page.getByText("الجلسة معتمدة: تعديل التكلفة يغيّر المبلغ المعتمد")).toBeVisible();
  const approvedRow = page.getByTestId("count-variances").locator("tr", { hasText: "E2E-STK-1" });
  await approvedRow.locator("input").fill("75");
  const voided = page.waitForResponse((r) => r.url().includes("/surplus-costs/"));
  await page.getByRole("button", { name: "حفظ تكاليف الزيادة" }).click();
  expect((await voided).status()).toBe(200);
  await expect(page.getByText("عادت الجلسة مسودة وأُبطل اعتمادها")).toBeVisible();
  await expect(page.getByRole("heading", { name: "جلسة جرد (مسودة)" })).toBeVisible();
  await expect(page.getByRole("button", { name: "ترحيل", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "العدّ", exact: true }).click();
  await expect(page.locator("tr", { hasText: "E2E-STK-1" }).locator("input").first()).toHaveValue("8.00");
  await page.getByRole("button", { name: "الفروق", exact: true }).click();
  await page.getByRole("heading", { name: /سجل التغييرات/ }).click();
  await expect(page.getByText("تغيّرت تكلفة وحدة الزيادة بعد الاعتماد")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/7.5f-approval-voided-by-cost-change.png`, fullPage: true });
  // Back to 70 (the numbers below), submit again, approve again.
  await page.getByTestId("count-variances").locator("tr", { hasText: "E2E-STK-1" }).locator("input").fill("70");
  const restored = page.waitForResponse((r) => r.url().includes("/surplus-costs/"));
  await page.getByRole("button", { name: "حفظ تكاليف الزيادة" }).click();
  expect((await restored).status()).toBe(200);
  const resubmitted = page.waitForResponse((r) => r.url().includes("/submit/") && r.request().method() === "POST");
  await page.getByRole("button", { name: "إرسال للاعتماد" }).click();
  expect((await resubmitted).status()).toBe(202);
  await approver.goto(sessionUrl);
  const reapproved = approver.waitForResponse((r) => r.url().includes("/approve/") && r.request().method() === "POST");
  await approver.getByRole("button", { name: "اعتماد", exact: true }).click();
  expect((await reapproved).status()).toBe(200);
  await expect(approver.getByText("معتمدة").first()).toBeVisible();

  await page.reload();
  const posted = page.waitForResponse((r) => r.url().includes("/post/") && r.request().method() === "POST");
  await page.getByRole("button", { name: "ترحيل", exact: true }).click();
  expect((await posted).status()).toBe(200);
  await expect(page.getByText("مرحّلة").first()).toBeVisible();
  await expect(page.getByTestId("count-variances").locator("tr", { hasText: "E2E-STK-1" })).toContainText("140.00");
  await expectCellsUnderTheirHeaders(page);
  await page.screenshot({ path: `${SHOTS}/7.5f-count-posted.png`, fullPage: true });

  // The numbers, over HTTP.
  tb = await trialBalance(page);
  console.log(`PHASE12 after post: 1400=${JSON.stringify(tb.byCode["1400"])} 5070=${JSON.stringify(tb.byCode["5070"])} total Dr=${tb.totalDebit} Cr=${tb.totalCredit}`);
  expect(tb.byCode["1400"].balance).toBe("1740.00");
  // The 7.3 engine nets one entry per account (_post_journal_entry): the
  // 500.00 shortage and the 140.00 surplus post as Dr 5070 360 / Cr 1400 360.
  // The gross figures live on the moves and the variances tab.
  expect(Number(tb.byCode["5070"].debit) - Number(tb.byCode["5070"].credit)).toBe(360);
  expect(tb.byCode["5070"].balance).toBe("360.00");
  expect(tb.totalDebit).toBe(tb.totalCredit);
  const stk = await stockLevel(page, "E2E-STK-1");
  const ser = await stockLevel(page, "E2E-SER-1");
  console.log(`PHASE12 after post: E2E-STK-1=${JSON.stringify(stk)} E2E-SER-1=${JSON.stringify(ser)}`);
  expect([stk.qty, stk.avg, stk.value]).toEqual(["8.00", "92.5000", "740.00"]);
  expect([ser.qty, ser.value]).toEqual(["2.00", "1000.00"]);

  await approver.context().close();
});

test("7.5: reversing the count on the screen", async ({ page }) => {
  const { sessionUrl } = JSON.parse(fs.readFileSync(SESSION_FILE, "utf-8"));
  await page.goto(sessionUrl);
  await page.getByRole("button", { name: "عكس القيد", exact: true }).click();
  await field(page, "reason").fill("e2e: عكس جلسة الجرد");
  const reversed = page.waitForResponse((r) => r.url().includes("/reverse/") && r.request().method() === "POST");
  await page.getByRole("button", { name: "حفظ", exact: true }).click();
  expect((await reversed).status()).toBe(201);
  await page.waitForURL((url) => url.pathname !== sessionUrl && /\/dashboard\/inventory\/stock\/[0-9a-f-]{36}$/.test(url.pathname));
  await page.goto(sessionUrl);
  await expect(page.getByText("معكوسة").first()).toBeVisible();
  // The variances stay readable on a reversed session (the screenshot
  // must not be taken before the table has loaded).
  await expect(page.getByTestId("count-variances").locator("tr", { hasText: "E2E-STK-1" })).toContainText("140.00");
  await expect(page.getByTestId("count-variances").locator("tr", { hasText: "E2E-SER-1" })).toContainText("−500.00");
  await page.screenshot({ path: `${SHOTS}/7.5f-count-reversed.png`, fullPage: true });
  await expectCellsUnderTheirHeaders(page);

  const tb = await trialBalance(page);
  console.log(`PHASE12 after reverse: 1400=${JSON.stringify(tb.byCode["1400"])} 5070=${JSON.stringify(tb.byCode["5070"])} total Dr=${tb.totalDebit} Cr=${tb.totalCredit}`);
  expect(tb.byCode["1400"].balance).toBe("2100.00");
  expect(tb.byCode["5070"].balance).toBe("0.00");
  expect(tb.totalDebit).toBe(tb.totalCredit);
  const stk = await stockLevel(page, "E2E-STK-1");
  const ser = await stockLevel(page, "E2E-SER-1");
  console.log(`PHASE12 after reverse: E2E-STK-1=${JSON.stringify(stk)} E2E-SER-1=${JSON.stringify(ser)}`);
  expect([stk.qty, stk.avg, stk.value]).toEqual(["6.00", "100.0000", "600.00"]);
  expect([ser.qty, ser.avg, ser.value]).toEqual(["3.00", "500.0000", "1500.00"]);
});
