# Rule 29 voucher source_type case - investigation (2026-10-19)

Scope: investigation only. No code changed, nothing committed. Live touched only via
`BEGIN READ ONLY` + `default_transaction_read_only=on` against infra-postgres-1.

## Verdict

The open marker in docs/SYSTEM_ANALYSIS.md rule 29 ("fath 2026-10-06, lam yuslah ba'd" =
"opened 2026-10-06, not fixed yet") is STALE. The code was fixed in da735fa (7.2.7a) and
source_type was frozen by a DB trigger in ec799f8 (7.2.7b, migration 0042, applied on
live 2026-10-08 12:53:51 UTC). Live data: 41 voucher rows, 0 wrong, 0 unresolvable,
0 inconsistent. It is neither a data problem nor an open code problem. The only open item
is the stale doc text.

## 1. The invariant, and what the vouchers path does differently

Invariant (7.2.7, sec. 8.7): every new JournalEntry declares its producer in
`produced_by`, a TextChoices member enforced by a DB CheckConstraint (never blank, never
an undeclared value); `content_type/object_id` (a real GenericFK) say which record it
concerns; `source_type/source_id` are frozen. No writer may set them, and trigger
`protect_source_type_source_id_trigger` rejects any INSERT with a non-blank value and any
UPDATE that changes them.

The vouchers path does NOT differ any more. `backend/apps/vouchers/services.py:740-764`
today (line 742 is now inside `JournalEntry.objects.create(`, not a source_type write):

    produced_by=_VOUCHER_PRODUCED_BY[voucher.voucher_type],
    content_type=ContentType.objects.get_for_model(Voucher),
    object_id=voucher.id,

with the closed mapping at services.py:40-44:

    _VOUCHER_PRODUCED_BY = {
        Voucher.VoucherType.RECEIPT: JournalEntry.ProducedBy.VOUCHER_RECEIPT,
        Voucher.VoucherType.PAYMENT: JournalEntry.ProducedBy.VOUCHER_PAYMENT,
        Voucher.VoucherType.SETTLEMENT: JournalEntry.ProducedBy.VOUCHER_SETTLEMENT,
    }

An unmapped type raises KeyError at posting. `source_type=f"voucher_..."` is gone:

    $ git log --oneline -S'_VOUCHER_PRODUCED_BY' -- backend/apps/vouchers/services.py
    da735fa Sprint 7.2.7a (step 1-2): produced_by enum + DB-enforced CheckConstraint, 6th writer converted, ...
    ec799f8 Sprint 7.2.7b: freeze source_type/source_id - stop all 7 writers first, then a real Postgres trigger

Live's running code (infra-backend-1) contains it:

    grep -c "_VOUCHER_PRODUCED_BY\["      /app/apps/vouchers/services.py  -> 1
    grep -c 'source_type=f"voucher_'      /app/apps/vouchers/services.py  -> 0

What still uses `f"voucher_{voucher.voucher_type}"` (services.py:708, 734, 849, 859) is the
document-numbering key and the approvals document type, a different namespace that does
not write to JournalEntry.source_type. It is outside this case. It is the same
dynamic-string pattern, and I have not audited it.

## 2. Consequence today on live data (literal output)

Live state:

    accounting | 0042_freeze_source_type_source_id      (latest accounting migration on live)
    protect_posted_journal_entry_trigger  | accounting_journalentry
    protect_source_type_source_id_trigger | accounting_journalentry
    freeze_applied = 2026-10-08 12:53:51.966893+00

All journal entries, source_type x produced_by x content model:
    == A. all JE: source_type x produced_by x content model
            source_type        |        produced_by        | ct_model | count 
    ---------------------------+---------------------------+----------+-------
                               | manual                    |          |    13
     asset_disposal            | asset_disposal            |          |     2
     asset_disposal_correction | asset_disposal_correction |          |     1
     invoice                   | invoice                   | invoice  |    11
     invoice_void              | invoice_void              | invoice  |     6
     opening_balance           | opening_balance           |          |     1
     recurring                 | recurring                 |          |    20
     voucher_payment           | voucher_payment           | voucher  |    21
     voucher_receipt           | voucher_receipt           | voucher  |    20
    (9 rows)

Voucher rows checked from both sides:

    == C. legacy voucher_* rows: resolution and consistency
     total | source_id_unresolved | type_mismatch_vs_voucher | produced_by_ne_source_type | object_id_ne_source_id | ct_not_voucher | cross_tenant | unknown_value 
    -------+----------------------+--------------------------+----------------------------+------------------------+----------------+--------------+---------------
        41 |                    0 |                        0 |                          0 |                      0 |              0 |            0 |             0
    (1 row)
    
    == D. produced_by voucher_* rows: object resolves, type agrees, back-pointer agrees
     total | object_unresolved | type_mismatch | voucher_points_elsewhere_non_reversal 
    -------+-------------------+---------------+---------------------------------------
        41 |                 0 |             0 |                                     0
    (1 row)
    
    == E. any row with non-blank source_type created after freeze migration applied
     count 
    -------
         0
    (1 row)
    
            freeze_applied         
    -------------------------------
     2026-10-08 12:53:51.966893+00
    (1 row)
    

Entries created on live since the freeze, and voucher totals:

    produced_by | count | max
    (0 rows)
    vouchers_total | posted | posted_without_je
                46 |     41 |                 0

Counts: wrong 0, unresolvable 0, inconsistent 0, of 41. The 41 rows are exactly the
"41 of 58" in the Phase 0 report. All were written before the freeze; every one carries
source_type == produced_by, source_id == object_id, and a content_type of voucher that
resolves to a voucher of the same tenant and type.

Note: no journal entry of any kind has been created on live since 2026-10-08 12:53 UTC.
So the converted voucher path has passed its tests but has not yet posted on live.

## 3. Data problem or code problem?

Neither. Data: 0 rows need correcting. Per tenant, all 41 rows are consistent:

    == B. voucher_* rows per tenant
        subdomain     | legacy_src | produced_by_voucher | post_freeze_only 
    ------------------+------------+---------------------+------------------
     fatma            |          3 |                   3 |                0
     smoke-1790517278 |          2 |                   2 |                0
     smoke-1790517412 |          2 |                   2 |                0
     smoke-1790517666 |          2 |                   2 |                0
     smoke-1790517844 |          2 |                   2 |                0
     smoke-1790518479 |          2 |                   2 |                0
     smoke-1790526634 |          2 |                   2 |                0
     smoke-1790526700 |          2 |                   2 |                0
     smoke-1790677349 |          2 |                   2 |                0
     smoke-1790677457 |          2 |                   2 |                0
     smoke-1790677534 |          2 |                   2 |                0
     smoke-1790680258 |          2 |                   2 |                0
     smoke-1790680519 |          2 |                   2 |                0
     smoke-1790687314 |          2 |                   2 |                0
     smoke-1790688060 |          2 |                   2 |                0
     smoke-1790702394 |          2 |                   2 |                0
     smoke-1790702774 |          2 |                   2 |                0
     smoke-1790716658 |          2 |                   2 |                0
     smoke-1790768055 |          2 |                   2 |                0
     smoke-1790768158 |          2 |                   2 |                0
    (20 rows)

Only 3 rows are in fatma; the other 38 are in 19 archived smoke-* tenants. Code: already
converted. The trigger makes any regression fail loudly with an error, not silently.

## 4. What a fix would touch

Only docs/SYSTEM_ANALYSIS.md: change rule 29's parenthetical "(opened 2026-10-06, not
fixed yet)" to a closure pointing at da735fa (writer converted), ec799f8/0042 (freeze,
live 2026-10-08), and this report's counts, plus a matching sec. 11 line. It needs no
code change, no migration, and no write to any accounting table. Rules 31 and 40 are not
engaged.

Optional and separate (not this case): decide whether the numbering/approvals keys at
services.py:708/734/849/859 should get the same closed-mapping treatment.

Side observation, out of scope: asset_disposal (2), asset_disposal_correction (1),
opening_balance (1), and recurring (20) rows have no content_type. I have not checked
whether that is intended by the 0040 backfill.
