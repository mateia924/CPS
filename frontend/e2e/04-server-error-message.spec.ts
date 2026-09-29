import { test, expect, type Page } from "@playwright/test";
import * as path from "path";

/** Sprint 6.5.14 item 7: a raw, non-JSON API response (Django's own
 * bare 500 page, an nginx 502/504 HTML page) must never reach a
 * screen as literal text — one unified message everywhere
 * (lib/api.ts's generalError(), "non_json_response" sentinel), not a
 * login-only patch. `page.route()` fulfills a real API call with a
 * fake HTML error body — no backend change needed to reproduce this
 * deterministically, and no real tenant is touched. Two screens on
 * purpose: the unauthenticated login POST (where this bug was first
 * reported live, against tenant "fatma") and an authenticated
 * dashboard PATCH — proving the fix lives in the shared request()
 * helper, not duplicated per screen. */

const AUTH_DIR = path.join(__dirname, ".auth");
const HTML_500_BODY = "<!doctype html>\n<html><head><title>Internal Server Error</title></head><body><h1>Internal Server Error</h1></body></html>";
const UNIFIED_MESSAGE = "خطأ في الخادم — حاول مرة أخرى بعد قليل";

function field(page: Page, name: string) {
  return page.locator(`[data-field="${name}"]`).locator("input, select, textarea").first();
}

async function assertNoRawHtmlLeaked(page: Page) {
  const bodyText = await page.locator("body").innerText();
  expect(bodyText).not.toContain("<!doctype");
  expect(bodyText).not.toContain("<html");
  expect(bodyText).not.toContain("Internal Server Error");
}

test("6.5.14 item 7: a raw HTML 500 on login never shows literal HTML — unified message instead", async ({
  page,
}) => {
  await page.route("**/api/auth/login/", (route) =>
    route.fulfill({ status: 500, contentType: "text/html", body: HTML_500_BODY })
  );

  await page.goto("/login");
  await field(page, "subdomain").fill("does-not-matter");
  await field(page, "email").fill("someone@example.test");
  await field(page, "password").fill("WhateverPass!2026");
  await page.getByRole("button", { name: "تسجيل الدخول" }).click();

  await expect(page.getByText(UNIFIED_MESSAGE)).toBeVisible();
  await assertNoRawHtmlLeaked(page);
});

test("6.5.14 item 7: a raw HTML 502 on an authenticated dashboard screen also shows the unified message", async ({
  browser,
}) => {
  const context = await browser.newContext({ storageState: path.join(AUTH_DIR, "state.json") });
  const page = await context.newPage();

  await page.route("**/api/legal-entities/**", (route) => {
    if (route.request().method() === "PATCH") {
      return route.fulfill({ status: 502, contentType: "text/html", body: HTML_500_BODY });
    }
    return route.continue();
  });

  await page.goto("/dashboard/settings/company");
  await expect(field(page, "name")).not.toHaveValue("");
  await page.getByRole("button", { name: "حفظ التعديلات", exact: true }).first().click();

  await expect(page.getByText(UNIFIED_MESSAGE)).toBeVisible();
  await assertNoRawHtmlLeaked(page);

  await context.close();
});
