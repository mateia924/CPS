import { test, expect, Page, Route } from "@playwright/test";
import * as path from "path";

/** Sprint 8.2 (rule 38): paying supplier bills, walked in a real browser on
 * a fresh smoke-* tenant (scripts/e2e_access.sh), every record entered
 * through the UI — a supplier, a bank, three bills; a partial payment from
 * the bill's «سداد» link through the payment-voucher screen; a supplier
 * advance on the voucher screen applied from the bill screen; «دفع نقدي
 * الآن»; then the payables aging, the supplier statement and the weekly
 * payables screen. Each report is also opened with its API forced to fail
 * (a 500 with Django's HTML page): it must name the failure and never read
 * as an empty result (block 8.0.2). */

const SUBDOMAIN = process.env.E2E_SUBDOMAIN!;
const EMAIL = process.env.E2E_OWNER_EMAIL!;
const PASSWORD = process.env.E2E_OWNER_PASSWORD!;
const SHOTS = path.join(__dirname, "../../docs/uat/screens/8.2");

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

async function noRefusal(page: Page) {
  await page.waitForLoadState("networkidle");
  await expect(page.locator('[data-state="forbidden"], [data-state="server-error"], [data-state="not-found"]')).toHaveCount(0);
}

async function selectByText(page: Page, name: string, text: string) {
  const select = field(page, name);
  const value = await select.locator("option", { hasText: text }).first().getAttribute("value");
  expect(value, `${name}: no option containing «${text}»`).toBeTruthy();
  await select.selectOption(value!);
}

async function postedBill(page: Page, supplier: string, billNumber: string, amount: string, dueDate: string) {
  await page.goto("/dashboard/purchasing/bills");
  await noRefusal(page);
  await selectByText(page, "supplier", supplier);
  await field(page, "bill_number").fill(billNumber);
  await field(page, "date").fill("2026-10-01");
  await field(page, "due_date").fill(dueDate);
  await field(page, "line_type_0").selectOption("expense");
  await field(page, "description_0").fill(`بند ${billNumber}`);
  await selectByText(page, "account_0", "5100");
  await field(page, "unit_price_0").fill(amount);
  await selectByText(page, "tax_code_0", "Z — ");
  const created = page.waitForResponse((r) => r.url().endsWith("/purchasing/bills/") && r.request().method() === "POST");
  await page.locator('[data-testid="supplier-bill-form"]').getByRole("button", { name: "حفظ" }).click();
  expect((await created).status()).toBe(201);
  await page.waitForURL(/\/dashboard\/purchasing\/bills\/[0-9a-f-]{36}$/);
  await page.getByRole("button", { name: "إرسال للاعتماد" }).click();
  await page.getByRole("button", { name: "اعتماد", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.locator("input").fill("لا مالك آخر نشط — اختبار 8.2");
  await dialog.getByRole("button", { name: "تأكيد" }).click();
  await page.getByRole("button", { name: "ترحيل" }).click();
  await expect(page.getByText("مرحّلة", { exact: true }).first()).toBeVisible();
  return page.url();
}

const html500 = (route: Route) =>
  route.fulfill({ status: 500, contentType: "text/html", body: "<h1>Server Error (500)</h1>" });

test.beforeAll(() => {
  expect(SUBDOMAIN && EMAIL && PASSWORD, "run through scripts/e2e_access.sh").toBeTruthy();
});

test("8.2: pay supplier bills from the voucher and the bill screens; aging, statement, weekly; forced failures", async ({ page }) => {
  test.setTimeout(300_000);
  await login(page);

  await test.step("a supplier and a bank, through their screens", async () => {
    await page.goto("/dashboard/suppliers");
    await noRefusal(page);
    await field(page, "name").fill("مورد السداد");
    const supplier = page.waitForResponse((r) => r.url().includes("/parties/suppliers/") && r.request().method() === "POST");
    await page.getByRole("button", { name: "إضافة" }).first().click();
    expect((await supplier).status()).toBe(201);

    await page.goto("/dashboard/treasury/banks");
    await noRefusal(page);
    await field(page, "name").fill("بنك السداد");
    const bank = page.waitForResponse((r) => r.url().includes("/api/banks/") && r.request().method() === "POST");
    await page.getByRole("button", { name: "إضافة", exact: true }).first().click();
    expect((await bank).status()).toBe(201);
  });

  let partialBillUrl = "";
  await test.step("bill 3,000 paid 1,000 through «سداد» -> the payment-voucher screen", async () => {
    partialBillUrl = await postedBill(page, "مورد السداد", "PAY-3000", "3000", "2026-10-10");
    await page.getByRole("link", { name: "سداد بسند صرف" }).click();
    await page.waitForURL("**/dashboard/treasury/vouchers/payment?**");
    await noRefusal(page);
    await selectByText(page, "treasury_id", "بنك السداد");
    await expect(field(page, "line_type")).toHaveValue("bill");
    await expect(field(page, "supplier_bill").locator("option:checked")).toContainText("PAY-3000");
    await field(page, "amount_fc").fill("1000");
    const made = page.waitForResponse((r) => r.url().endsWith("/api/vouchers/") && r.request().method() === "POST");
    await page.getByRole("button", { name: "سند صرف جديد" }).click();
    expect((await made).status()).toBe(201);
    const posted = page.waitForResponse((r) => r.url().includes("/post/") && r.request().method() === "POST");
    await page.getByRole("button", { name: "ترحيل" }).first().click();
    expect((await posted).status()).toBe(200);
    await page.screenshot({ path: `${SHOTS}/01-payment-voucher-from-bill.png`, fullPage: true });

    await page.goto(partialBillUrl);
    await noRefusal(page);
    await expect(page.getByText(/المستحق للمورد: 2,000\.00/)).toBeVisible();
    await expect(page.locator('[data-testid="bill-payments"]')).toContainText("1,000.00");
    await page.screenshot({ path: `${SHOTS}/02-bill-partially-paid.png`, fullPage: true });
  });

  await test.step("an advance of 500 on the voucher screen, applied from a bill of 800", async () => {
    await page.goto("/dashboard/treasury/vouchers/payment");
    await noRefusal(page);
    await selectByText(page, "treasury_id", "بنك السداد");
    await field(page, "party_role").selectOption("supplier");
    await selectByText(page, "party", "مورد السداد");
    await field(page, "line_type").selectOption("advance");
    await field(page, "amount_fc").fill("500");
    const made = page.waitForResponse((r) => r.url().endsWith("/api/vouchers/") && r.request().method() === "POST");
    await page.getByRole("button", { name: "سند صرف جديد" }).click();
    expect((await made).status()).toBe(201);
    const posted = page.waitForResponse((r) => r.url().includes("/post/") && r.request().method() === "POST");
    await page.getByRole("button", { name: "ترحيل" }).first().click();
    expect((await posted).status()).toBe(200);

    await postedBill(page, "مورد السداد", "PAY-800", "800", "2026-10-25");
    const advances = page.locator('[data-testid="open-advances"]');
    await expect(advances).toContainText("500.00");
    await page.getByRole("button", { name: "تخصيص على الفاتورة" }).click();
    await expect(page.getByText(/المستحق للمورد: 300\.00/)).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/03-advance-applied.png`, fullPage: true });
  });

  await test.step("«دفع نقدي الآن» on a bill of 450", async () => {
    await postedBill(page, "مورد السداد", "PAY-450", "450", "2026-11-30");
    await selectByText(page, "pay_from", "بنك السداد");
    await page.getByRole("button", { name: "ادفع المتبقي الآن" }).click();
    await expect(page.locator('[data-testid="pay-now-result"]')).toContainText("PV-");
    await expect(page.getByText(/المستحق للمورد: 0\.00/)).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/04-pay-now.png`, fullPage: true });
  });

  await test.step("payables aging: the open remainders in their buckets", async () => {
    await page.goto("/dashboard/reports/aging?side=payable");
    await noRefusal(page);
    await page.locator('[data-field="as_of"], .form-field').filter({ hasText: "كما في" }).locator("input").fill("2026-11-24");
    await page.getByRole("button", { name: "إرسال", exact: true }).first().click();
    // The reference column is our PINV number, as invoices show theirs.
    const result = page.locator('[data-testid="aging-result"]');
    const rows = result.locator("table").last().locator("tbody tr");
    await expect(rows.filter({ hasText: "2,000.00" })).toContainText("31-60");  // PAY-3000, due 10-10, 45 days on 11-24
    await expect(rows.filter({ hasText: "300.00" }).filter({ hasNotText: "2,300.00" })).toContainText("0-30");  // PAY-800, due 10-25
    await expect(rows).toHaveCount(2);  // PAY-450 was paid in full
    await page.screenshot({ path: `${SHOTS}/05-payables-aging.png`, fullPage: true });
  });

  await test.step("supplier statement: documents linked, open bills listed", async () => {
    await page.goto("/dashboard/reports/statement");
    await noRefusal(page);
    await page.getByPlaceholder(/ابحث بالاسم/).fill("مورد السداد");
    await page.getByRole("button", { name: "بحث" }).click();
    await page.getByRole("button", { name: /مورد السداد/ }).first().click();
    const statement = page.locator('[data-testid="statement-result"]');
    await expect(statement).toBeVisible();
    await expect(statement.getByRole("link", { name: "عرض المستند" }).first()).toBeVisible();
    const open = page.locator('[data-testid="open-bills"]');
    await expect(open).toContainText("PAY-3000");
    await expect(open).toContainText("PAY-800");
    await expect(open).not.toContainText("PAY-450");
    await page.screenshot({ path: `${SHOTS}/06-supplier-statement.png`, fullPage: true });
  });

  await test.step("weekly payables", async () => {
    await page.goto("/dashboard/purchasing/payables-by-week");
    await noRefusal(page);
    await expect(page.locator('[data-testid="payables-by-week"]')).toContainText("PAY-3000");
    await page.screenshot({ path: `${SHOTS}/07-payables-by-week.png`, fullPage: true });
  });

  await test.step("forced failures: the new report screens name it, never an empty result", async () => {
    await page.route("**/api/reports/aging/?**", html500);
    await page.goto("/dashboard/reports/aging?side=payable");
    await page.waitForLoadState("networkidle");
    await expect(page.locator('main [data-state="server-error"]').first()).toBeVisible();
    await expect(page.locator('[data-testid="aging-result"]')).toHaveCount(0);
    await page.screenshot({ path: `${SHOTS}/08-aging-forced-500.png`, fullPage: true });
    await page.unroute("**/api/reports/aging/?**");

    await page.route("**/api/purchasing/payables-by-week/?**", html500);
    await page.goto("/dashboard/purchasing/payables-by-week");
    await page.waitForLoadState("networkidle");
    await expect(page.locator('main [data-state="server-error"]').first()).toBeVisible();
    await expect(page.locator('[data-testid="payables-by-week"]')).toHaveCount(0);
    await page.screenshot({ path: `${SHOTS}/09-weekly-forced-500.png`, fullPage: true });
    await page.unroute("**/api/purchasing/payables-by-week/?**");

    await page.route("**/statement/?**", html500);
    await page.goto("/dashboard/reports/statement");
    await page.getByPlaceholder(/ابحث بالاسم/).fill("مورد السداد");
    await page.getByRole("button", { name: "بحث" }).click();
    await page.getByRole("button", { name: /مورد السداد/ }).first().click();
    await page.waitForLoadState("networkidle");
    await expect(page.locator('main [data-state="server-error"]').first()).toBeVisible();
    await expect(page.locator('[data-testid="statement-result"]')).toHaveCount(0);
    await page.screenshot({ path: `${SHOTS}/10-statement-forced-500.png`, fullPage: true });
  });
});
