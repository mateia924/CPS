import { test, expect, Page } from "@playwright/test";
import * as path from "path";

/** Sprint 8.1 (rule 38): the supplier-bill and expenses screens, walked in
 * a real browser with every record entered through the UI — on a fresh
 * smoke-* tenant scripts/e2e_access.sh registers (purchasing on, the
 * registration's own supplier_bill approval rule: Owner). The tenant also
 * has a Viewer, so the Owner is not the only active user: approving their
 * own bill goes through the emergency-approval dialog, as it would on a
 * real two-user tenant.
 *
 * The spec's fixed numbers, read back from the screens: rent 10,000 +
 * 15% deductible -> 11,500; telecoms 1,000 + 15% non-deductible -> 1,150;
 * a foreign service under RC 5,000 -> 750 both sides, 5,000 owed; an asset
 * line 20,000 -> an asset «not in service» linked to the bill; a repeated
 * supplier invoice number -> the field's own error; a 5,000 mandatory-
 * attachment rule -> the rule's text at submit. Then the expenses list. */

const SUBDOMAIN = process.env.E2E_SUBDOMAIN!;
const EMAIL = process.env.E2E_OWNER_EMAIL!;
const PASSWORD = process.env.E2E_OWNER_PASSWORD!;
const SHOTS = path.join(__dirname, "../../docs/uat/screens/8.1");

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
  await expect(page.locator('[data-state="forbidden"]')).toHaveCount(0);
}

async function createSupplier(page: Page, name: string) {
  await page.goto("/dashboard/suppliers");
  await noRefusal(page);
  await field(page, "name").fill(name);
  const saved = page.waitForResponse((r) => r.url().includes("/parties/suppliers/") && r.request().method() === "POST");
  await page.getByRole("button", { name: "إضافة" }).first().click();
  expect((await saved).status()).toBe(201);
}

async function selectByText(page: Page, name: string, text: string) {
  const select = field(page, name);
  const value = await select.locator("option", { hasText: text }).first().getAttribute("value");
  expect(value, `${name}: no option containing «${text}»`).toBeTruthy();
  await select.selectOption(value!);
}

interface LineSpec {
  type: "service" | "expense" | "asset";
  price: string;
  taxCode: string;
  account?: string;
  description?: string;
  deductible?: boolean;
  assetName?: string;
  assetCategory?: string;
}

async function newBill(page: Page, supplier: string, billNumber: string, line: LineSpec) {
  await page.goto("/dashboard/purchasing/bills");
  await noRefusal(page);
  await selectByText(page, "supplier", supplier);
  await field(page, "bill_number").fill(billNumber);
  await field(page, "date").fill("2026-10-15");
  await field(page, "line_type_0").selectOption(line.type);
  if (line.type === "asset") {
    await field(page, "asset_name_0").fill(line.assetName!);
    await field(page, "asset_category_0").selectOption(line.assetCategory!);
  } else {
    if (line.description) await field(page, "description_0").fill(line.description);
    await selectByText(page, "account_0", line.account!);
  }
  await field(page, "unit_price_0").fill(line.price);
  await selectByText(page, "tax_code_0", `${line.taxCode} — `);
  if (line.deductible === false) await field(page, "vat_deductible_0").uncheck();
  // Wrapped: an async function returning a bare promise would wait for it.
  return { created: page.waitForResponse((r) => r.url().endsWith("/purchasing/bills/") && r.request().method() === "POST") };
}

async function saveNewBill(page: Page, { created }: { created: Promise<import("@playwright/test").Response> }) {
  await page.locator('[data-testid="supplier-bill-form"]').getByRole("button", { name: "حفظ" }).click();
  expect((await created).status()).toBe(201);
  await page.waitForURL(/\/dashboard\/purchasing\/bills\/[0-9a-f-]{36}$/);
  await noRefusal(page);
}

async function approveAndPost(page: Page) {
  await page.getByRole("button", { name: "إرسال للاعتماد" }).click();
  await expect(page.getByText("بانتظار الاعتماد", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "اعتماد", exact: true }).click();
  // The Owner created it and is the only Owner: the emergency dialog.
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.locator("input").fill("لا مالك آخر نشط — اختبار 8.1");
  await dialog.getByRole("button", { name: "تأكيد" }).click();
  await page.getByRole("button", { name: "ترحيل" }).click();
  await expect(page.getByText("مرحّلة", { exact: true }).first()).toBeVisible();
  await expect(page.locator('[data-testid="bill-header"]')).toContainText("JV-");
}

test.beforeAll(() => {
  expect(SUBDOMAIN && EMAIL && PASSWORD, "run through scripts/e2e_access.sh").toBeTruthy();
});

test("8.1: supplier bills entered through the UI post the spec's numbers; expenses list", async ({ page }) => {
  test.setTimeout(240_000);
  await login(page);
  await createSupplier(page, "مؤجر المكتب");
  await createSupplier(page, "شركة الاتصالات");
  await createSupplier(page, "Foreign Consulting Ltd");
  await createSupplier(page, "مورد المعدات");

  await test.step("rent 10,000 + 15% deductible", async () => {
    const created = await newBill(page, "مؤجر المكتب", "R-2026-10", {
      type: "expense", price: "10000", taxCode: "S", account: "5100", description: "إيجار أكتوبر",
    });
    await saveNewBill(page, created);
    const totals = page.locator('[data-testid="bill-totals"]');
    await expect(totals).toContainText("10,000.00");
    await expect(totals).toContainText("1,500.00");
    await expect(totals).toContainText("11,500.00");
    await approveAndPost(page);
    await page.screenshot({ path: `${SHOTS}/01-rent-posted.png`, fullPage: true });
  });

  await test.step("telecoms 1,000 + 15% non-deductible -> 1,150", async () => {
    const created = await newBill(page, "شركة الاتصالات", "T-889", {
      type: "expense", price: "1000", taxCode: "S", account: "5100", description: "اتصالات أكتوبر", deductible: false,
    });
    await saveNewBill(page, created);
    const totals = page.locator('[data-testid="bill-totals"]');
    await expect(totals).toContainText("150.00");
    await expect(page.getByText(/المستحق للمورد: 1,150\.00/)).toBeVisible();
    await approveAndPost(page);
    await page.screenshot({ path: `${SHOTS}/02-telecoms-capitalized.png`, fullPage: true });
  });

  await test.step("foreign service RC 5,000 -> 750 both sides, 5,000 owed", async () => {
    const created = await newBill(page, "Foreign Consulting Ltd", "FC-17", {
      type: "service", price: "5000", taxCode: "RC", account: "5100", description: "استشارات",
    });
    await saveNewBill(page, created);
    const totals = page.locator('[data-testid="bill-totals"]');
    await expect(totals).toContainText("750.00");
    await expect(page.getByText(/المستحق للمورد: 5,000\.00/)).toBeVisible();
    await approveAndPost(page);
    await page.screenshot({ path: `${SHOTS}/03-reverse-charge.png`, fullPage: true });
  });

  await test.step("asset line 20,000 -> an asset not in service, linked to the bill", async () => {
    const created = await newBill(page, "مورد المعدات", "EQ-55", {
      type: "asset", price: "20000", taxCode: "O", assetName: "رافعة شوكية", assetCategory: "equipment",
    });
    await saveNewBill(page, created);
    await approveAndPost(page);
    const assetLink = page.locator('[data-testid="bill-lines"] a[href^="/dashboard/assets/"]');
    await expect(assetLink).toHaveCount(1);
    const billNumber = (await page.locator("h1").innerText()).split(" ").pop()!;
    await page.screenshot({ path: `${SHOTS}/04-asset-line-posted.png`, fullPage: true });
    await assetLink.click();
    await noRefusal(page);
    await expect(page.locator('[data-testid="asset-source-bill"]')).toContainText(billNumber);
    await expect(page.getByText("لم يدخل الخدمة").first()).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/05-asset-not-in-service.png`, fullPage: true });
    // No date is filled in for a bill asset, so starting depreciation now
    // must reach the server's refusal, not silently use the bill date.
    await expect(field(page, "in_service_date")).toHaveValue("");
    await page.getByRole("button", { name: "بدء الإهلاك" }).click();
    await expect(page.getByText(/لم يُحدَّد تاريخ بدء الخدمة/).first()).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/05b-depreciation-refused.png`, fullPage: true });
    await page.goto("/dashboard/assets");
    await noRefusal(page);
    await expect(page.locator('[data-testid="asset-not-in-service"]').first()).toBeVisible();
  });

  await test.step("a repeated supplier invoice number is refused on the field", async () => {
    const { created } = await newBill(page, "مؤجر المكتب", "R-2026-10", {
      type: "expense", price: "100", taxCode: "S", account: "5100",
    });
    await page.locator('[data-testid="supplier-bill-form"]').getByRole("button", { name: "حفظ" }).click();
    expect((await created).status()).toBe(400);
    await expect(page.locator('[data-field="bill_number"]')).toContainText("مسجَّل من قبل لهذا المورد");
    await page.screenshot({ path: `${SHOTS}/06-duplicate-number.png`, fullPage: true });
  });

  await test.step("a mandatory-attachment rule at 5,000 refuses the submit with its text", async () => {
    await page.goto("/dashboard/settings/attachment-rules");
    await noRefusal(page);
    await field(page, "doc_type").selectOption("supplier_bill");
    await field(page, "min_amount_base").fill("5000");
    await field(page, "required_category").selectOption("fatura_original");
    const rule = page.waitForResponse((r) => r.url().includes("/attachment-rules/") && r.request().method() === "POST");
    await page.getByRole("button", { name: "إضافة", exact: true }).first().click();
    expect((await rule).status()).toBe(201);

    const created = await newBill(page, "مؤجر المكتب", "R-2026-11", {
      type: "expense", price: "6000", taxCode: "S", account: "5100",
    });
    await saveNewBill(page, created);
    await page.getByRole("button", { name: "إرسال للاعتماد" }).click();
    await expect(page.getByText(/المستند يتطلب مرفق «فاتورة المورد الأصلية» لأنه يتجاوز/)).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/07-attachment-required.png`, fullPage: true });
  });

  await test.step("expenses: the two EXPENSE lines, at what their account was debited", async () => {
    await page.goto("/dashboard/purchasing/expenses");
    await noRefusal(page);
    const table = page.locator("table").last();
    await expect(table.locator("tbody tr")).toHaveCount(2);
    await expect(table).toContainText("اتصالات أكتوبر");
    await expect(table).toContainText("1,150.00");
    await expect(table).toContainText("إيجار أكتوبر");
    await expect(table).toContainText("10,000.00");
    await expect(page.locator('[data-testid="expenses-total"]')).toContainText("11,150.00");
    await page.screenshot({ path: `${SHOTS}/08-expenses.png`, fullPage: true });
  });

  await test.step("the bills list", async () => {
    await page.goto("/dashboard/purchasing/bills");
    await noRefusal(page);
    await page.screenshot({ path: `${SHOTS}/09-bills-list.png`, fullPage: true });
  });
});
