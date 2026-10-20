# seed_purchasing_defaults: who it skips, and where Accountant's grant comes from (2026-10-20)

Read-only. The real seed was not run. Source: the live dry-run of 2026-10-20 07:20Z
(docs/reports/2026-10-20-seed-purchasing-dryrun.md), plus the code at HEAD 1065a3d.

## 1. Why 35 of 50 tenants were skipped

There is one reason, and it applies to all 35.

**The tenant's status is `archived`.** This is a rule in the command, not a bug:

- `backend/apps/purchasing/management/commands/seed_purchasing_defaults.py:42` builds the target list:
  `Tenant.objects.exclude(status=Tenant.Status.ARCHIVED)`.
- Line 43-45 names every excluded tenant in its output.
- Line 52-53 refuses an archived tenant named with `--tenant`.

The same convention is used by `add_missing_system_accounts` and `load_withholding_codes`: "archived tenants are
excluded and named". The 35 are `debug-tenant-x` plus 34 `smoke-*` tenants, all archived by
`archive_smoke_tenants`.

No tenant was skipped for any other reason. All 15 non-archived tenants (active and trial alike, fatma included)
were processed, and all 15 would change.

## 2. Which roles gain which permissions, and where Accountant's grant comes from

The dry-run output is identical for all 15 tenants: 1cps, acme, browsersim1, cps, externalcheck, fatma,
nonrootcheck, retest, secondco, sprint15test, sprint1live, sprint35smoke, sprint3smoke, xx, xxx.

| Role (system) | Gains | Spec 8.0 says |
|---|---|---|
| Purchasing (created new) | purchasing.view, purchasing.manage | "دور افتراضي «مشتريات» بـ view/manage" (sprint-8.md block 8.0, line 100). **Matches.** |
| Owner | purchasing.view, purchasing.manage, purchasing.post, purchasing.override_match | Not named. Follows from Owner = every permission (`SYSTEM_ROLES["Owner"] = None`, access/services.py:124). R-8.5 says override_match is a separate permission; nothing says Owner lacks it. |
| **Accountant** | **purchasing.view, purchasing.post** | **Not in the spec.** Block 8.0 names only the Purchasing role. |
| Sales, Viewer, Warehouse Keeper, any custom role | nothing | — |

### Where the Accountant grant comes from

1. The seed does not name roles itself. It walks the registration definition:
   `backend/apps/purchasing/services.py:112`
   `for name, codes in SYSTEM_ROLES.items():`
   `backend/apps/purchasing/services.py:113`
   `wanted = [c for c in purchasing_codes if codes is None or c in codes]`
   It then adds the missing codes at `services.py:126` (`role.permissions.add(...)`).
2. The grant itself is in that definition:
   `backend/apps/access/services.py:163` `"purchasing.view",`
   `backend/apps/access/services.py:164` `"purchasing.post",`
   They are inside `SYSTEM_ROLES["Accountant"]` (opened at access/services.py:125), with the comment at
   access/services.py:158-162: "same split as inventory above — view and post, not manage ... and not
   override_match (Owner only by default)".
3. Origin: commit bd16dff (Sprint 8.0, 2026-10-19), per `git log -L163,164:backend/apps/access/services.py`.

**It is a decision the 8.0 implementation made by analogy with 7.0's D17**, where the spec did say
"المحاسب inventory.view + inventory.post". It is not in sprint-8.md. It is not logged in SYSTEM_ANALYSIS.md §11.
Nothing in docs/ records it as a decision.

It applies in two places:

- **Registration:** every tenant registered since bd16dff already has it.
- **The seed,** if run as it stands: the 15 existing tenants, including fatma's one Accountant (the `*.test` smoke
  account).

### What needs your word before the real seed

- Keep Accountant view+post (record it as a decision in §11), or remove it from `SYSTEM_ROLES["Accountant"]`.
- Removing it also changes registration. Tenants registered since 2026-10-19 on dev/staging would keep the
  grant unless reverted. **Live: no tenant created since 2026-10-19.** Checked read-only on infra-postgres-1:
  `tenants_tenant WHERE created_at >= '2026-10-19'` returned 0 rows. So no live tenant holds it yet.
