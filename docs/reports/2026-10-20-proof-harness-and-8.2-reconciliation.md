# 2026-10-20 - proof harness mount, and the 8.2 reconciliation gate

## 1. Did the proofs write to /opt/cps?

Before the fix: yes. The earlier statement "the proofs mount the live tree"
was accurate. It also hid the real problem.

- The pytest container did mount /opt/cps read-only (`-v /opt/cps:/workspace:ro`).
- However, prove_guard.sh itself ran on the host. It edited the guard IN
  /opt/cps/<FILE>, kept a backup in /var/tmp/prove_guard.<pid>, and put the
  original back from an EXIT trap.
- The dev stack bind-mounts backend/ and frontend/ from /opt/cps. So for the
  whole length of each proof the guard was really off in the live tree, and
  dev was serving that tree.
- A SIGKILL, an OOM kill or a host reboot skips the trap. Any of these would
  have left the guard disabled in /opt/cps. The nightly backup.sh, the next
  deploy.sh build, or the next commit would then have picked it up.

On the shallow clone: prove_guard.sh in this repo never used one. Git history
for scripts/prove_guard.sh shows edit-in-place plus trap restore since it was
created. So this was not a one-off deviation in this run. The script itself
did not match the design you describe. I should have flagged that the first
time I wrote "mount the live tree".

What I did:

- Stopped the 8.2 runner with TERM by pid. All 13 runs that had started
  restored byte-identical. No disabled guard was left anywhere:
  `git diff` showed none of the proof edits, and sha256 matched the
  pre-run copies.
- Rewrote scripts/prove_guard.sh to work on a copy, not a clone. A clone would
  miss the uncommitted 8.2 code, and guards are proven before their commit.
  The new flow:
  - rsync the working tree to /var/tmp/cps-proof-<pid>/repo, without
    node_modules, .next and .env;
  - disable the guard in the copy only;
  - run pytest in the `test` image as uid 1001, with the COPY mounted
    read-only;
  - for UI proofs (--e2e), run a throwaway `next dev` from the copy's
    frontend/, with a throwaway nginx on port 3012.
- /opt/cps is never written. The real file's sha256 is checked before and
  after every run, and the run fails if it changed.
- The EXIT trap now removes only the copy and the throwaway containers. If a
  run is killed, the next run deletes the leftover copy (its owner pid is
  dead).

Killed-run proof, done today (SIGKILL sent after the copy was mutated):

    copy mutated: 1
    SIGKILL sent to 654626
    real file sha unchanged: yes
    real file guard line present: 1
    /var/tmp/cps-proof-654626                  <- only the copy was left behind
    [prove_guard] removing a leftover copy from a killed run: /var/tmp/cps-proof-654626
    no leftover copies

The full 8.2 proof set (11 backend + 3 UI) is being re-run from scratch under
the new harness. Results from the old harness are discarded.

## 2. Reconciliation (dev, cps-dev-db, tenant smoke-alloc-1792500800)

The dev, staging and live databases all had 0 allocation rows. Reconciling
against nothing would prove nothing. So before migrating I seeded real
allocations through the public API: receipt vouchers allocated to invoices,
including one partial, one reversed, and one USD invoice settled at a
different rate.

### Before vouchers 0007 (vouchers_voucherallocation)

| invoice        | voucher        | allocated     | base@inv | base settled | fx diff | reversed |
|----------------|----------------|---------------|----------|--------------|---------|----------|
| INV-2026-00001 | RV-2026-00001  | 2000.00       | 2000.00  | 2000.00      | 0.00    | f        |
| INV-2026-00002 | RV-2026-00002  | 1000.00       | 1000.00  | 1000.00      | 0.00    | f        |
| INV-2026-00002 | RV-2026-00003  | 500.00        | 500.00   | 500.00       | 0.00    | f        |
| INV-2026-00003 | RV-2026-00004  | 1000.00       | 1000.00  | 1000.00      | 0.00    | t        |
| INV-2026-00004 | RV-2026-00005  | 1000.00 USD   | 3750.00  | 3800.00      | 50.00   | f        |

Per invoice (computed from the allocations, compared with the stored
paid/status):

| invoice      | total | active alloc | paid | balance | payment_status | status |
|--------------|-------|--------------|------|---------|----------------|--------|
| INV-1        | 2000  | 2000         | 2000 | 0       | paid           | paid   |
| INV-2        | 3000  | 1500         | 1500 | 1500    | partial        | issued |
| INV-3        | 1000  | 0            | 0    | 1000    | unpaid         | issued |
| INV-4 (USD)  | 1000  | 1000         | 1000 | 0       | paid           | paid   |

Checksums before: rows 5, md5 of all rows 9d0f0cd4788b59cbb97e81794c80e61f,
invoice_id NULL = 0.

### After

- After 0007: rows 5, the same md5 9d0f0cd4788b59cbb97e81794c80e61f, and the
  same per-invoice table.
  - Rows with both FKs set: 0. Rows with neither set: 0.
  - Constraint present with convalidated = f (NOT VALID).
  - A deliberate bad UPDATE (setting invoice_id NULL) was refused with
    "violates check constraint voucherallocation_exactly_one_target" and
    rolled back.
- After 0008 (VALIDATE CONSTRAINT): convalidated = t, and the same md5 and
  per-invoice table.

Verdict: no allocation, amount, FX difference or invoice status changed.

### Final design built (as decided)

VoucherAllocation has two nullable FKs, invoice and supplier_bill, plus a
database CHECK constraint.

- Name: `voucherallocation_exactly_one_target`
- Definition, vouchers/migrations/0007_allocation_target_invoice_or_supplier_bill.py:

      CHECK = (
          "(invoice_id IS NOT NULL AND supplier_bill_id IS NULL) "
          "OR (invoice_id IS NULL AND supplier_bill_id IS NOT NULL)"
      )
      ALTER TABLE vouchers_voucherallocation ADD CONSTRAINT
          voucherallocation_exactly_one_target CHECK ({CHECK}) NOT VALID

  The model state carries the same CheckConstraint (SeparateDatabaseAndState).
- vouchers/migrations/0008_validate_allocation_target_constraint.py:

      ALTER TABLE vouchers_voucherallocation VALIDATE CONSTRAINT voucherallocation_exactly_one_target

- As Postgres stores it (pg_get_constraintdef):

      CHECK ((((invoice_id IS NOT NULL) AND (supplier_bill_id IS NULL)) OR
             ((invoice_id IS NULL) AND (supplier_bill_id IS NOT NULL))))

### scripts/backup.sh before each dev migration

`make migrate` runs scripts/backup.sh first. Lines 144-146 of docs/ops/backups.log:

    2026-10-20T15:54:31+03:00  5317b1e  dev/cps-db-20261020-155428.sql.gz.gpg  make migrate  db=postgres/cps#7691754161498136610   <- before vouchers 0007
    2026-10-20T15:55:19+03:00  5317b1e  dev/cps-db-20261020-155517.sql.gz.gpg  make migrate  db=postgres/cps#7691754161498136610   <- before vouchers 0008
    2026-10-20T15:59:54+03:00  5317b1e  dev/cps-db-20261020-155952.sql.gz.gpg  make migrate  db=postgres/cps#7691754161498136610   <- before accounting 0045, vouchers 0009, purchasing 0003

None of these migrations has touched staging or live. There is no deploy in
this block.
