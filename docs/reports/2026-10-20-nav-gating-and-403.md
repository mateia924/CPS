# Block 8.0.1 step 2: sidebar gating and the 403 state (2026-10-20)

Two defects the 8.0 live browser walk found (docs/reports/2026-10-19-live-deploy-afe501f.md),
both fixed generically. Not deployed. Verified on the dev stack (`next dev`, port 3002).

## (a) Sidebar links to screens the user cannot open

### Count before the fix (frontend/src/app/dashboard/layout.tsx at b7458f5)

- **50 nav entries** (approval inbox in the top bar, 48 sidebar links, profile at the bottom).
- **25 permission-gated**: approval inbox (any of 4 approve permissions), receipt/payment/
  settlement vouchers (vouchers.view), 6 accounting screens and 7 reports (accounting.view),
  company settings, cost centers, roles and users, full parties view, approval rules,
  document numbering, attachment rules, fiscal years.
- **25 not permission-gated** (some had a module feature flag or simplified-mode check,
  but no permission):

| Entry | Feature gate it had | Permission now (what the screen's list API enforces) |
|---|---|---|
| Dashboard | - | none, stated reason: landing page, /dashboard/summary/ needs only a login |
| Customers | - | parties.view (/parties/customers/) |
| Items | - | products.view |
| Invoices | - | invoices.view |
| Suppliers | purchasing | parties.view |
| **Purchase settings** | purchasing | **purchasing.view** (the walk's defect) |
| Stock receipts / issues / transfers / counts | inventory | inventory.view (/stock-documents/) |
| Stock balances | inventory | inventory.view |
| Warehouses | inventory | inventory.view |
| Item categories | inventory | products.view |
| Units of measure | inventory | products.view |
| Inventory settings | inventory | inventory.view |
| Banks / cash boxes / custodies / exchange rates | treasury | treasury.view |
| Bank reconciliation dashboard | treasury | treasury.view (checked inside the view) |
| Assets | assets | assets.view |
| Employees | - | parties.view |
| Organization | org feature / Owner | organization.view (feature/Owner rule kept) |
| Affiliates | not simplified | parties.view |
| Profile | - | none, stated reason: the user's own account |

Each permission was read off the backend (`resolve()` of the screen's list endpoint ->
`permission_map`), in the dev container, not guessed from the label.

### Fix

- `frontend/src/lib/nav.ts`: the sidebar as data. The `NavGate` type requires every entry
  to carry either `permission` (one code or any-of) or `ungated: "<reason>"`; an entry with
  neither does not compile. Feature/simplified-mode gates kept as `when`. A section with no
  visible entry renders no heading.
- `layout.tsx` renders from that table. After: **48 of 50 entries permission-gated, 2 ungated
  with a stated reason** (dashboard, profile).

## (b) A 403 rendered a blank main area

Cause: screens load with `api.get(...).then(set)` and `if (!data) return null`; a 403 rejects
with no handler, so nothing renders. `DataTable`'s own load has no catch either.

Fix, in the shared layer: `frontend/src/components/ScreenAccess.tsx`, mounted by the
dashboard layout around every screen. A 403 `ApiError` that no screen handled arrives as an
`unhandledrejection`; the shell then shows a named state above the screen:
"ليس لديك صلاحية" / "لا تملك الصلاحية اللازمة لفتح هذه الشاشة أو جزء منها. اطلب من مالك
الحساب منحك الصلاحية من «الأدوار والمستخدمون»." Screens that catch their own 403 (form saves,
the inbox count) keep their own message. Children still render, so a screen where only a side
request was refused keeps working. Navigating away clears it.

### 404 and 500: yes, they also fall through (not fixed here, as asked)

From the browser walk below, as a Viewer:

| Case | What the user sees |
|---|---|
| Unknown route `/dashboard/no-such-screen` | Next's default page, English, outside the app shell: "404 This page could not be found." Not blank, but no sidebar and not Arabic. |
| API 404, missing record `/dashboard/invoices/<zero uuid>` | **Blank main area** |
| API 404, module off (`/dashboard/inventory/settings`, inventory off) | **Blank main area** |
| API 500 with JSON body (simulated by request interception) on purchasing settings | **Blank main area** |
| API 500 with HTML body (simulated) on a DataTable list (items) | Worse than blank: the list says "لا توجد بيانات لعرضها." (no data), i.e. it claims the list is empty |

The same `ScreenAccess` hook can carry 404 and 5xx states; that is a decision for you.

## Side fix found by the new test: opening balances

The generic check (open every link the Viewer sees, none may land on the no-permission state)
failed on `/dashboard/accounting/opening-balances`. The screen loaded `/parties/`
(parties.view_all) for the create form's party picker in one `Promise.all` with the status
table. For a Viewer (accounting.view only) that whole load failed, so even before this block
the status table and filters stayed empty with no message. Creating needs accounting.manage
on the API anyway. Now the status and the list load for everyone with accounting.view; the
create form and its data (tree, parties, cost centers) only for accounting.manage.

## Tests

`frontend/e2e/14-screen-access.spec.ts`, run by the new `scripts/e2e_access.sh` (own smoke
tenant through the registration API, purchasing on, a Viewer via create_test_user, archived
on exit; passwords random per run and off the command line, rule 50). Added to
`scripts/e2e.sh` as phase 14.

1. "sidebar shows no link the user cannot open": suppliers link visible (section is there),
   purchase settings link absent, then every visible link opened, none refused.
2. "a refused screen names the reason instead of rendering blank": GET
   /api/purchasing/settings/ answers 403 and `main [data-state="forbidden"]` is visible with
   the heading.

Limit, stated: test 1's loop detects a refused screen through the 403 state, so with the 403
handler removed that loop cannot see refusals (test 1 passed during proof b). The explicit
purchase-settings assertion does not depend on it.

Results: spec 14 2/2 pass; full `scripts/e2e.sh` phases 1-14 pass (exit 0); `tsc --noEmit`
clean; `npm run build` passes (its prebuild runs all 7 structural checks), on a copy of the
tree so the dev server's `.next` was not touched.

## Rule 49 proofs (scripts/prove_guard.sh, new `--e2e` mode)

`prove_guard.sh` gained `--e2e`: the spec runs through `scripts/e2e_access.sh`, its
Playwright container named by prove_guard so `restore()` removes it; same EXIT-trap restore
and byte-compare as before. Expected names match the list reporter's failed line.

Proof (a), gate removed from the purchase-settings entry:

    [prove_guard] guard disabled in frontend/src/lib/nav.ts:
    -      { href: "/dashboard/purchasing/settings", label: "purchaseSettings", permission: "purchasing.view" },
    +      { href: "/dashboard/purchasing/settings", label: "purchaseSettings", ungated: "rule-49 proof: gate removed" },
      x  1 14-screen-access.spec.ts:38:5 > sidebar shows no link the user cannot open (7.0s)
        Error: expect(locator).toHaveCount(expected) failed
        Locator:  locator('aside.sidebar').locator('a[href="/dashboard/purchasing/settings"]')
        Expected: 0
        Received: 1
        > 42 |   await expect(sidebar.locator('a[href="/dashboard/purchasing/settings"]')).toHaveCount(0);
    [prove_guard] PROVEN: sidebar shows no link the user cannot open failed with the guard disabled.
    [prove_guard] restored: frontend/src/lib/nav.ts is byte-identical to its saved copy.

Proof (b), 403 handler disabled:

    [prove_guard] guard disabled in frontend/src/components/ScreenAccess.tsx:
    -      if (event.reason instanceof ApiError && event.reason.status === 403) {
    +      if (false && event.reason instanceof ApiError && event.reason.status === 403) {
      x  2 14-screen-access.spec.ts:53:5 > a refused screen names the reason instead of rendering blank (7.3s)
        Error: expect(locator).toBeVisible() failed
        Locator: locator('main [data-state="forbidden"]')
        Expected: visible
        Error: element(s) not found
        > 59 |   await expect(state).toBeVisible();
    [prove_guard] PROVEN: a refused screen names the reason instead of rendering blank failed with the guard disabled.
    [prove_guard] restored: frontend/src/components/ScreenAccess.tsx is byte-identical to its saved copy.

The page snapshot Playwright saved at that failure shows `- main` with no children: the
main area was blank. (Playwright's check/cross glyphs and the title arrow are replaced with
x and > here to keep this file ASCII-safe.)

## Rule 38: browser walk

Headless Chromium (Playwright image, as in the 2026-10-19 live walk), dev stack, a fresh
smoke tenant with purchasing on, logged in as a **Viewer (no purchasing.view)**. Screenshots:
`docs/uat/screens/8.0.1/`.

- Sidebar: Dashboard; Sales: customers, items, invoices; **Purchasing: suppliers only (no
  purchase settings)**; Accounting 6; Reports 7; HR: employees; Settings: attachment rules;
  Profile.
- `/dashboard/purchasing/settings`: API `403 GET /api/purchasing/settings/`. Main area now
  reads: "ليس لديك صلاحية" then "لا تملك الصلاحية اللازمة لفتح هذه الشاشة أو جزء منها. اطلب من
  مالك الحساب منحك الصلاحية من «الأدوار والمستخدمون»." (`02-purchasing-settings-viewer.png`)
- Dev mode only: Next's dev indicator still counts the rejection ("1 Issue" pill); production
  builds have no such indicator.

## On live, once deployed

Live has no `purchasing.*` rows in `access_permission` at all (see the dry-run report). So
after this ships, the purchase-settings link disappears for **every** live user, Owners
included, until `seed_purchasing_defaults` runs. Today every one of them gets the blank 403
page instead. Suppliers stays visible where purchasing is on (parties.view).
