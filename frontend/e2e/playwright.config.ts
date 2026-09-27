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
    trace: "off",
  },
});
