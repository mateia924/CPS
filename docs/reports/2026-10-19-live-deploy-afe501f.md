# Live deploy of afe501f (Sprint 7.2.9 through 8.0), 2026-10-19

Result: **OK**. `scripts/deploy.sh` exit 0, 23:17:29 to 23:19:04 (95s). deploys.log records
a clean run, with no dirty-tree note:
`2026-10-19T23:19:04+03:00  afe501fc777a28df10a14c7ee6ab30862719fc77  OK  deploy.sh`.
`seed_purchasing_defaults` was not run, nor its dry run.

## Gates

| Step | Result |
|---|---|
| clean-tree guard | named the two standing exclusions (`?? docs/uat/screens/6.5.8/8.0-withholding-codes-examples.png`, `?? infra/fail2ban/`); nothing else dirty |
| secrets preflight | passed |
| build | backend, celery_worker, frontend built from afe501f |
| **abort check before gate 1** | `email backend for live: django.core.mail.backends.dummy.EmailBackend` (23:18:19). The wrapper logged GUARD OK and the deploy continued. |
| 1 backup | `cps-db-20261019-231819.sql.gz.gpg`, target `postgres/cps#7686947508661833762` |
| 2 migrate | 10/10 applied, 23:18:28 to 23:18:31 (list below) |
| 3 setup_rls | passed |
| 4 verify_rls | 52/52 tenant-scoped tables have tenant_isolation |
| 5 add_missing_system_accounts | 60 accounts created, 4 in each of 15 active tenants (SUPPLIER_ADVANCES 1350, LANDED_COST_CLEARING 2130, WHT_PAYABLE 2250, PURCHASE_PRICE_VARIANCE 5080); 35 archived tenants excluded; 0 corrected; 0 failures |
| 6 check_chart_health | 0 findings, 0 accepted exceptions |
| 7 start | previous images tagged `:rollback-20261019-231847` (infra-backend `e6cec526a131`, infra-celery_worker `2a1512ef2e53`, infra-frontend `5e6f3fa39706`); external images untouched |
| 8 ready | 9s (23:18:53 to 23:19:02) |
| 9 smoke | ALL CHECKS PASSED, trial balance debit=credit=**105250.59** |

Rollback, if needed:
```
cd /opt/cps/infra && docker tag infra-backend:rollback-20261019-231847 infra-backend:latest && docker tag infra-celery_worker:rollback-20261019-231847 infra-celery_worker:latest && docker tag infra-frontend:rollback-20261019-231847 infra-frontend:latest && docker compose --env-file /opt/cps/.env -f docker-compose.yml -f docker-compose.local.yml up -d --no-build && docker compose --env-file /opt/cps/.env -f docker-compose.yml -f docker-compose.local.yml restart nginx
```
That rollback restores the code only. The 10 migrations stay applied, and the old code
runs against the new schema.

## Unexpected: live postgres and minio were recreated before gate 1

At 23:18:10, while the email-backend line was being read, compose recreated
`infra-postgres-1` and `infra-minio-1`. Cause: both use `env_file: ../.env`, and the
`EMAIL_BACKEND` line changed that file, so `docker compose run --rm backend` saw new config
for its dependencies and recreated them. Any later `run` or `up` would have done the same.
Staging did not show it because `.env.staging` did not change.

Effect:
- postgres restarted on its persistent volume, and both were healthy within about 7s;
- the old app containers lost their DB connections for those seconds, before the backup
  gate ran.

No data effect: database_identity() is unchanged after the restart (below). I reported it
live and did not interrupt the run. **Lesson for DEPLOY.md:** any `.env` edit restarts
postgres on the next deploy, and the run must state that beforehand.

## Step 3 checks

1. **database_identity()**, the real function (`apps/tenants/management/commands/migrate.py:87`)
   run inside the new live backend: `postgres/cps#7686947508661833762`, equal to the
   expected value.
2. **smoke:** green, trial balance **105250.59**.
3. **Migrations and indexes** (READ ONLY transaction): all 10 are present in
   `django_migrations`, applied 20:18:28 to 20:18:31 UTC:
   - accounting.0043
   - accounts.0005
   - approvals.0020
   - inventory.0007, 0008, 0009, 0010
   - purchasing.0001
   - parties.0007, parties.0008

   `showmigrations --plan` shows 0 unapplied. `pg_index`: **0** with `indisvalid = false`,
   0 with `indisready = false`.
4. **Startup line:** backend and celery_worker both log
   `email backend: django.core.mail.backends.dummy.EmailBackend`.
5. **First live backups.log line written by this deploy** (line 141):
   `2026-10-19T23:18:22+03:00  afe501f  cps-db-20261019-231819.sql.gz.gpg  deploy.sh afe501fc777a28df10a14c7ee6ab30862719fc77  db=postgres/cps#7686947508661833762`

## Browser walk on live (port 3000)

Headless Chromium (Playwright image, same as e2e), logged in as the smoke account
`accountant@fatma.test`. The walk only navigated: no form was submitted except the login.
Screenshots are in the session scratchpad, not in the repo.

| Screen | What it shows |
|---|---|
| Inventory balances (`/dashboard/inventory/balances`) | Renders, with the empty-state row "لا توجد بيانات لعرضها."; no API or console errors |
| Stock receipts (`/dashboard/inventory/stock/receipts`) | Renders, empty; no errors. **No receipt to open:** live has **0 stock documents in any tenant** (`inventory_stockdocument` is empty, read-only check). Opening one would mean creating one on live, which I did not do. |
| Stock count (`/dashboard/inventory/stock/counts`) | Renders: title "جرد المخزون", status filter, search, and the columns number, date, warehouse, scope, variance value, status. Empty, so **no session to open**, same reason. No errors. |
| Approvals inbox (`/dashboard/approvals`) | "صندوق الاعتماد", with "لا توجد مستندات بانتظار اعتمادك."; no errors |
| **Purchasing settings** (`/dashboard/purchasing/settings`) | **The main area is completely blank.** The API answered `403 GET /api/purchasing/settings/`. The sidebar still shows "إعدادات المشتريات" under "المشتريات". |

### Purchasing settings: two findings

- **Cause of the 403:** expected for now. fatma's Accountant role predates 8.0 and has no
  `purchasing.view`, and only `seed_purchasing_defaults` adds it (not run, by your order).
- **Defect (frontend, 8.0):** on a 403 the screen renders nothing, with no message, and the
  sidebar shows the link to a role without the permission. The e2e phase 13 never sees this,
  because its tenant is registered after 8.0 and has the permission. I propose a fix in its
  own block: show the same no-permission message other screens use, and hide the link
  without `purchasing.view`. Not done; it needs your word.
- When the seed runs, the screen shows its settings. The withholding-codes table will still
  be empty on existing tenants until `load_withholding_codes` runs; that is a separate
  decision.

## Waiting for the owner

1. The `seed_purchasing_defaults --all-tenants --dry-run` on live (it rolls back), then a
   report per tenant, then your word before the real run.
2. Whether and when `load_withholding_codes` runs on live.
3. The purchasing-settings 403 blank page and sidebar link fix (above).
4. A DEPLOY.md line: an `.env` edit recreates postgres and minio on the next deploy.
5. This report is not committed yet.
