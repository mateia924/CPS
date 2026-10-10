import { test, expect } from "@playwright/test";

/** Sprint 7.2.9 (§8.9, owner review 2026-10-10): the one path phase
 * A-7's staging walkthrough structurally CANNOT exercise, because
 * staging is IP-only and the manual subdomain field is always shown
 * there (frontend/src/app/reset-password/page.tsx's own §8.9 note).
 * On a real per-tenant domain the field is hidden — this proves the
 * value it would have held still reaches the confirm request's body,
 * not left blank/undefined, which would silently break every
 * password reset on live. No real backend call needed: the confirm
 * endpoint is faked via page.route() (same technique as
 * 07-voucher-insufficient-balance-message.spec.ts) purely to capture
 * what the frontend actually sent, before it gets a (deliberately
 * fake) 400 back. `fatma.localhost` resolves to loopback with zero
 * configuration (RFC 6761) — same reasoning
 * frontend/src/lib/subdomain.ts's own module comment gives for why a
 * real tenant subdomain in production looks exactly like this. */

test("host-derived subdomain reaches the confirm request even though the field is hidden", async ({ page }) => {
  let capturedBody: Record<string, unknown> | null = null;

  await page.route("**/api/auth/password-reset/confirm/", (route) => {
    capturedBody = route.request().postDataJSON();
    return route.fulfill({ status: 400, contentType: "application/json", body: JSON.stringify({ token: ["invalid"] }) });
  });

  const base = new URL(process.env.E2E_BASE_URL || "http://localhost:3002");
  await page.goto(`${base.protocol}//fatma.${base.host}/reset-password?token=does-not-matter`);

  // The auto-detected-subdomain branch: companyLabel text, no manual
  // input field at all.
  await expect(page.locator('[data-field="subdomain"]')).toHaveCount(0);

  await page.locator('[data-field="new_password"] input').fill("WhateverPass!2026");
  await page.getByRole("button", { name: "تعيين كلمة السر" }).click();

  await expect.poll(() => capturedBody).not.toBeNull();
  expect(capturedBody!.subdomain).toBe("fatma");
  expect(capturedBody!.token).toBe("does-not-matter");
});
