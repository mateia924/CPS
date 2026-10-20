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

## 3. Design question: should the seed be additive-only?

The proposal: the seed creates accounts, withholding codes, the permission catalog rows, the new Purchasing
role and the purchasing approval rules, and **modifies no existing role**. Nothing changes for any tenant's
users until its owner grants the role deliberately.

### What the seed does today versus additive-only

| Item | Today's seed | Additive-only |
|---|---|---|
| 4 `purchasing.*` rows in `access_permission` (global catalog) | creates | creates (needed before anyone can grant them) |
| Purchasing system role with view/manage, 0 users | creates | creates |
| Owner role + view/manage/post/override_match | **adds** | **no** |
| Accountant role + view/post | **adds** | **no** |
| 5 purchasing approval rules (min 0 -> Owner) | creates | creates |
| Purchasing system accounts | not this command (`add_missing_system_accounts`, already on live via deploy) | unchanged |
| Withholding codes (SA, as examples) | not this command (`load_withholding_codes`) | can be run additively; invisible until the module is used |

### For additive-only

- Purchasing is not released. Today on live nobody, Owners included, holds purchasing.*, and the 403 the
  8.0.1 walk found was correct behaviour. Additive-only keeps it exactly so until each owner chooses.
- No user's access changes as a side effect of an infrastructure command. fatma's Accountant (the smoke
  account, but the rule is the point) would not silently gain posting rights on a module nobody approved.
- The owner can grant it herself:
  - The roles API lets a roles.manage holder edit any role's permissions, system roles included. Only
    deletion is blocked for system roles: access/views.py:45-52, 74.
  - Once the catalog rows exist she can add purchasing.* to Owner or Accountant, or assign users the new
    Purchasing role.
  - That is a recorded, deliberate act (AuditLog `access.role.updated`), not a seed side effect.
- The approval rules are safe to create in advance. No supplier bill exists yet, and a missing rule means
  auto-approval (the 7.4 incident), so the rules are protective, not a change in anyone's access.

### Against additive-only

- **Owner = every permission stops being true** for pre-8.0 tenants. `SYSTEM_ROLES["Owner"] = None`
  (access/services.py:124) is the definition registration uses. A tenant registered tomorrow gets an Owner
  with purchasing.*; fatma's Owner would not. The same role name would mean two different things depending
  on registration date, until each owner edits it.
- Old and new tenants diverge the same way for Accountant, unless registration is also changed. That is the
  open question in section 2.
- Every owner has a manual step before purchasing works at all, even for themselves. Without being told, an
  owner sees the module switched on and still gets "no permission".

### Recommendation: additive-only, plus two explicit decisions

1. **Make the seed additive-only.** It creates the catalog rows, the Purchasing role and the approval rules,
   and touches no existing role. Withholding codes are loaded by their own command, run separately, also
   additive.
   - This needs a code change to `seed_purchasing_defaults` (today it walks `SYSTEM_ROLES` and adds to every
     role, purchasing/services.py:112-126).
   - The `--dry-run` would then report "Owner/Accountant: unchanged".
   - Not built until you decide.
2. **Owner on existing tenants:** grant purchasing.* when the owner switches purchasing on for her tenant
   (the moment she asks for it), not by a seed run. Then "Owner = everything" holds again for every tenant
   that actually uses the module. Tenants that never use it never need it.
3. **Accountant in registration:** decide once, for new and old tenants alike (section 2). If kept, record
   it in §11. If not, remove `purchasing.view/post` from `SYSTEM_ROLES["Accountant"]` so new tenants stop
   getting what old ones would not.

**Nothing was run.** The seed has not been executed, with or without `--dry-run`, since the 07:20Z dry run in
docs/reports/2026-10-20-seed-purchasing-dryrun.md.
