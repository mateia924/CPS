# seed_purchasing_defaults --all-tenants --dry-run (LIVE) - 2026-10-20

Block 8.0.1, step 1. Read-only. The real seed was NOT run.

- Target: LIVE (`infra-backend-1` / `infra-postgres-1`), the deployed code (afe501f).
- Run at: 2026-10-20T07:20:30Z
- Command: `docker exec infra-backend-1 python manage.py seed_purchasing_defaults --all-tenants --dry-run`
- Exit code: 0

## Tenant count

- 50 tenants in `tenants_tenant`.
- 35 archived (debug-tenant-x + 34 `smoke-*`): excluded by the command, named in its output.
- **15 tenants processed; all 15 "would change".**

## What the command does and does not cover (read this first)

`seed_purchasing_defaults` touches exactly three things: role permissions, the
Purchasing role, and the five purchasing approval rules (plus the global permission
catalog via `seed_permissions()`). It does **not** create accounts and does **not**
load withholding codes. Those come from two other commands:

- accounts: `add_missing_system_accounts` (run by scripts/deploy.sh on every deploy)
- withholding codes: `load_withholding_codes` (no `--dry-run` flag; never run on live)

So the honest answer to "accounts it would create" and "withholding codes it would
load" is **none, for this command**. The current live state of both is given below
from read-only SELECTs so the gap is visible.

## Per tenant: what the dry-run would ADD

The output is identical for all 15 tenants:

| tenant | role created | Owner + | Accountant + | Purchasing + | approval rules created (min=0 -> Owner) |
|---|---|---|---|---|---|
| 1cps | Purchasing | view, manage, post, override_match | view, post | view, manage | 5 |
| acme | Purchasing | same | view, post | view, manage | 5 |
| browsersim1 | Purchasing | same | view, post | view, manage | 5 |
| cps | Purchasing | same | view, post | view, manage | 5 |
| externalcheck | Purchasing | same | view, post | view, manage | 5 |
| fatma | Purchasing | same | view, post | view, manage | 5 |
| nonrootcheck | Purchasing | same | view, post | view, manage | 5 |
| retest | Purchasing | same | view, post | view, manage | 5 |
| secondco | Purchasing | same | view, post | view, manage | 5 |
| sprint15test | Purchasing | same | view, post | view, manage | 5 |
| sprint1live | Purchasing | same | view, post | view, manage | 5 |
| sprint35smoke | Purchasing | same | view, post | view, manage | 5 |
| sprint3smoke | Purchasing | same | view, post | view, manage | 5 |
| xx | Purchasing | same | view, post | view, manage | 5 |
| xxx | Purchasing | same | view, post | view, manage | 5 |

(all permission codes are `purchasing.<x>`; the 5 rules are purchase_order,
supplier_bill, purchase_return, landed_cost, party_netting)

Role -> permission grants per tenant (8 grants, 120 in total):

- Owner: + purchasing.view, purchasing.manage, purchasing.post, purchasing.override_match
- **Accountant: + purchasing.view, purchasing.post  -- YES, Accountant is among them, in all 15 tenants.**
- Purchasing (new role): + purchasing.view, purchasing.manage

No grant to Sales, Viewer, Warehouse Keeper, or any custom (non-system) role.
No "MISSING system role" line and no "RULE NOT ACTIVE" line for any tenant.

Who is affected today (active users on the roles that gain permissions):

- fatma: Owner 3 active users, **Accountant 1 active user** (this user would gain
  purchasing.view and purchasing.post on the real run). That user is the smoke/test
  account (`*.test` address, the one the 2026-10-19 browser walk used), not a real
  fatma employee.
- every other tenant: Owner 1 active user, Accountant 0.
- Purchasing role: new, 0 users anywhere.

No tenant has any existing role named like "Purchasing" (system or custom, live or
soft-deleted), so the `unique_role_name_per_tenant` constraint cannot trip.

## Anything it would MODIFY rather than create

- Roles, role permissions, approval rules: **nothing modified**. The code only adds
  (`permissions.add`, `get_or_create`); no row is edited or removed.
- Global permission catalog (`access_permission`, shared by all tenants):
  `seed_permissions()` does `update_or_create` for every code.
  - **4 rows CREATED**: purchasing.view, purchasing.manage, purchasing.post,
    purchasing.override_match. They do not exist on live today (live has 47
    permission rows, code defines 51). This is why nobody on live can be granted
    purchasing.* yet.
  - **47 existing rows UPDATED with identical values**: every live description was
    compared against the deployed `DEFAULT_PERMISSIONS`; all 47 match exactly, so the
    UPDATE writes the same text back. No value changes.

## Accounts (not this command - live state, read-only)

All 15 non-archived tenants already hold the four 8.0 system accounts, created
2026-10-19 by the afe501f deploy's `add_missing_system_accounts`:

| system_key | code | parent |
|---|---|---|
| SUPPLIER_ADVANCES | 1350 | 1000 |
| LANDED_COST_CLEARING | 2130 | 2000 |
| WHT_PAYABLE | 2250 | 2000 |
| PURCHASE_PRICE_VARIANCE | 5080 | 5000 |

Every tenant got the spec code exactly (no suffixed fallback code), i.e. no code
collision happened. Nothing left to create; this seed creates no accounts.

## Withholding codes (not this command - live state, read-only)

| tenant | countries (legal entities) | codes present | `load_withholding_codes` would load |
|---|---|---|---|
| all 15 tenants | SA | 0 | SA, 3 each (NR-SERVICES 5%, NR-ROYALTIES 15%, NR-MANAGEMENT 20%), 45 total, as examples |

`purchasing_withholdingtaxcode` is empty on live. No tenant has an EG legal entity.

## Proof nothing was written

Same read-only snapshot (`BEGIN READ ONLY`, `default_transaction_read_only=on`) taken
immediately before and after the dry-run: row count plus an md5 over every row's full
text, per table.

| table | rows before | rows after | md5 before = after |
|---|---|---|---|
| access_permission | 47 | 47 | bf3d82a814d274a2b4a6d26f96565a03 (same) |
| access_role | 246 | 246 | 46962a6139811c44b87b38466359c40e (same) |
| access_role_permissions | 5002 | 5002 | 8572bb6877848a0c637b8e63382924dd (same) |
| approvals_approvalrule | 394 | 394 | e4a9cf9d92dd966d5a4c1e39e0d9575e (same) |
| purchasing_withholdingtaxcode | 0 | 0 | d41d8cd98f00b204e9800998ecf8427e (same) |
| accounting_account | 1718 | 1718 | 2d9103d1ec282e55e24d5833e56fdc7e (same) |
| tenants_tenant | 50 | 50 | cc0a12c5a21c180e3e18b25fb9623653 (same) |

One thing DID change, and it is not a row: the sequence
`access_role_permissions_id_seq` moved from 5174 to 5294 (+120 = 15 tenants x 8
grants). PostgreSQL sequences are not transactional, so the rolled-back INSERTs still
consumed ids. Effect: a 120-id gap in that table's bigint ids. No data meaning; stated
because "wrote nothing" should be exact. The other tables affected use UUID keys.

The dry-run itself works by doing the writes inside `transaction.atomic()` per tenant
and raising before commit; for ~15 short transactions it held row locks on the roles
it touched. fatma was not observably affected (no errors in output).

## Open points for the owner before the real run

1. Accountant gets purchasing.view + purchasing.post in every tenant, including
   fatma's one active accountant. That is what SYSTEM_ROLES says registration gives a
   new tenant; whether to grant it to an existing tenant's accountant is your call.
2. The run also creates 5 approval rules (Owner approves) per tenant; for fatma that
   is a workflow change the day supplier bills ship (8.1).
3. Withholding codes are a separate command that has no dry-run.
