# Sprint 8 spec vs. what 7.3-7.5 built (2026-10-19)

Step 1 of block 8.0. This was read-only: no engine code changed. Line numbers refer to HEAD
61967ea.

| Spec assumption | Verdict | Where it breaks |
|---|---|---|
| D9: a cost-only move (`StockMove qty=0, value>0`) | ABSENT | refused in validation; and the cost function would divide by zero |
| D3: `RECEIPT` with `source=GRN` | DIFFERENT | `RECEIPT` exists; no `source` field on `StockDocument` |
| D4 / R-8.1: average driven by a value-only adjustment | ABSENT | `_apply_cost` has no value-only branch |
| D7: generic allocation target | DIFFERENT | `VoucherAllocation.invoice` is a hard FK to `sales.Invoice` |

None of the four blocks 8.0. They land in 8.2 (D7), 8.4 (D3), 8.5 (R-8.1) and 8.6 (D9). Per the
freeze line in sprint-8.md, each of those blocks must name the engine change it makes.

## D9: cost-only stock move. ABSENT

`post_stock_document` (`backend/apps/inventory/services.py:902`) cannot post a move with zero
quantity and a non-zero value. Two separate places stop it:

1. `_validate_lines`, `services.py:311-312`, refuses before anything moves:

       if line.qty_base == 0:
           raise ValidationError(f"... -- لا حركة بكمية صفرية.")

2. Even with that check removed, `_apply_cost` (`services.py:650-690`) has no value-only
   path. With `m.qty == 0` it falls into the outflow branch (`else:`, line 665). There,
   `new_value = old_value - counter` *subtracts* the value (line 675). Then
   `m.unit_cost = _unit_cost(counter / abs(m.qty))` (line 686) divides by zero.

`_plan_document_moves` (`services.py:345-383`) also prices only `qty > 0` lines
(`fixed = _money(qty * line.unit_cost)`).

There is no DB constraint on `StockMove.qty_base` (inventory migrations 0005-0007 have no
CHECK). The block lives entirely in Python.

Needed in 8.6 (or 8.5, see R-8.1): a value-only move kind, through a new branch in
`_apply_cost`, never by relaxing the qty check for all kinds.

## D3: RECEIPT with source=GRN. DIFFERENT

`StockDocument.Kind` (`backend/apps/inventory/models.py:501-506`): `RECEIPT`, `ISSUE`,
`TRANSFER`, `COUNT`, `OPENING`. `RECEIPT` exists and posts Dr `INVENTORY` / Cr `GRNI` by
default (`services.py:362-363`: `counter = document.account or
get_required_system_account(tenant, "GRNI")`), which is what D3 wants.

`StockDocument` has **no `source` field**. Its fields are `legal_entity`, `warehouse`,
`to_warehouse`, `kind`, `number`, `date`, `party`, `account`, `reference`, `notes`,
`reverses`, `created_by`, `created_at`, `count_scope` (`models.py:519-548`). The posted
`JournalEntry` points at the `StockDocument` itself through `content_type/object_id`
(`services.py:737`, `produced_by=STOCK_DOCUMENT`).

Does the engine accept an externally supplied source? Only in the loose sense. Any caller
can create an APPROVED `StockDocument` with `party`/`account`/`reference` set and call
`post_stock_document(document, user)`, which takes no source argument. Nothing records that
a GRN produced it.

Needed in 8.4: a link from GRN to its internal `StockDocument`. The cheapest additive form is
an FK on `GoodsReceipt` to the `StockDocument` (no change to inventory). Alternatively a
nullable source FK on `StockDocument`, which would be an inventory change and must be named.

## D4 / R-8.1: moving average from a value-only adjustment. ABSENT

The average update is `_apply_cost` (`services.py:650-690`). It is driven only by quantity
moves. `avg_cost` is recomputed as `_unit_cost(new_value / new_qty)` (line 690), and
`_unit_cost` quantizes to 4 places (`_UNIT = Decimal("0.0001")`, lines 200 and 207-208). That
is consistent with "now 4 dp". `total_value` stays the authoritative number (comment at lines
186-195).

There is no function that adds value without quantity. The arithmetic would work, since a
value-only branch only needs `new_value = old_value + value` with `new_qty == old_qty` and
then the same line 690. But the branch does not exist, and the qty==0 path is broken as shown
under D9. The same gap blocks R-8.1 (8.5) and D9 (8.6). One engine change serves both. It
also needs R-8.1's rule for the part already issued (to `PURCHASE_PRICE_VARIANCE` by ratio),
which `_apply_cost` cannot know. The caller has to split the value first.

## D7: generic allocation target. DIFFERENT

The model is `VoucherAllocation` (`backend/apps/vouchers/models.py:252-286`), not
`Allocation`. Its target is a hard FK:

    invoice = models.ForeignKey("sales.Invoice", on_delete=models.PROTECT, related_name="allocations")

`sales.Invoice` is the customer invoice. It has no kind/direction field and carries
`paid_fc`, `balance_fc` and `payment_status`, which `post_voucher` updates. It is one per
INVOICE-type `VoucherLine` (OneToOne `voucher_line`). It cannot point at a `SupplierBill`
today.

D7 says "the same `Allocation` table with a generic target". Needed in 8.2: either a nullable
`supplier_bill` FK beside `invoice` plus a CHECK that exactly one is set (additive, explicit,
and the CHECK is DB-enforced), or a GenericFK. Recommendation: the two-FK form. A GenericFK
loses `on_delete=PROTECT` and the DB-level referential check that the voucher engine relies
on today.
