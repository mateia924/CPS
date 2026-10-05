import { defineConfig } from "@playwright/test";

/** Sprint 6.5.8: a real headless-browser click-through against the
 * running dev stack (nginx on http://localhost:3000, `make dev-up`
 * first) — runs inside the official Playwright Docker image via
 * `make e2e` (Alpine/musl, this repo's own frontend image, can't run
 * Playwright's Chromium build at all). One worker, no retries: this is
 * a UAT-style scripted walkthrough on a fresh smoke-* tenant, not a
 * flaky-prone unit test. */
export default defineConfig({
  testDir: ".",
  timeout: 60_000,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: {
    // Must match NEXT_PUBLIC_API_URL's own origin exactly (.env) — the
    // frontend's own fetch() calls that URL directly, and navigating
    // the browser to a *different* origin (e.g. localhost:3000, same
    // server, different origin) makes every API call a cross-origin
    // request that the backend's CORS config rejects at the preflight.
    baseURL: process.env.E2E_BASE_URL || "http://localhost:3000",
    screenshot: "off",
    // 2026-10-06 (03-non-emergency-approval regression investigation):
    // "off" meant this exact failure — a wrong value that never
    // self-corrected across the full retry window, not a slow one —
    // left zero network/DOM trail beyond error-context.md's own
    // auto-captured snapshot. retain-on-failure costs nothing on a
    // passing run (no trace written) and is exactly the artifact this
    // class of failure needs.
    trace: "retain-on-failure",
  },
});
