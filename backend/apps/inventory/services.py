from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Max, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounting.models import JournalEntry, JournalLine
from apps.accounting.services import (
    build_journal_lines_with_fx_rounding,
    get_required_system_account,
    post_journal_entry,
)
from apps.numbering.services import next_document_number
from apps.organization.services import company_entity_for
from apps.platform.models import AuditLog
from apps.platform.services import log_action

from .models import (
    Batch,
    BatchStock,
    InventorySettings,
    ItemCost,
    ItemUoM,
    SerialNumber,
    StockDocument,
    StockDocumentLine,
    StockLevel,
    StockMove,
    Warehouse,
)

# docs/catalog/industries.json's own item_features vocabulary
# (sprint-7.md's "المدخلات الملزمة" row): barcode, variants, units,
# units_m2_box, units_weight, serial, serial_imei, serial_vin, batch,
# batch_expiry, weight_karat, daily_price, part_numbers, bundles.
# Only the ones that map to an InventorySettings default are grouped
# here — "variants"/"daily_price"/"part_numbers"/"bundles" are per-item
# (apps.inventory models from later blocks), not a tenant-wide default.
_SERIAL_FEATURES = {"serial", "serial_imei", "serial_vin"}
_BATCH_FEATURES = {"batch", "batch_expiry"}
_UNITS_FEATURES = {"units", "units_m2_box", "units_weight"}


def apply_item_feature_defaults(tenant, item_features):
    """Sprint 7.0 (D18): called with a tenant's industry's own
    item_features list (docs/catalog/industries.json, or
    apps.packs.IndustryPack once 6.2 lands — D18 is explicit that
    whichever exists reads this the same way, no activity-specific
    code path either way). Sets InventorySettings' defaults for a NEW
    item category going forward — never retroactively changes an
    existing category's own already-chosen tracking (that's
    ItemCategory's own field, untouched here).

    Every effect here is driven purely by which feature strings are
    present — no per-activity branch — matching the project-wide "لا
    كود خاص بنشاط" rule."""
    features = set(item_features or [])
    settings_obj, _created = InventorySettings.objects.get_or_create(tenant=tenant)

    if features & _SERIAL_FEATURES:
        settings_obj.default_tracking = InventorySettings.Tracking.SERIAL
    elif features & _BATCH_FEATURES:
        settings_obj.default_tracking = InventorySettings.Tracking.BATCH

    if features & _UNITS_FEATURES:
        settings_obj.units_enabled = True
    if "barcode" in features:
        settings_obj.barcode_enabled = True
    if "weight_karat" in features:
        settings_obj.show_weight_karat_fields = True

    settings_obj.save()
    return settings_obj


def convert_qty_to_base(item, uom, qty):
    """Sprint 7.1 (D8 — sprint-7.md appendix: "كل سطر مستند يحمل uom +
    qty + qty_base المحسوبة خادميًا"). Not wired into any document
    model yet — StockDocumentLine (D5) is sprint 7.2/7.3's job — this
    is the one, reusable conversion every future document line will
    call, built now so it's never re-derived per-document the way the
    accounting debt definitions were (sprint 7.0.3's own lesson).

    `uom=None` or `uom == item.base_uom` means "already in the base
    unit" — factor 1, no ItemUoM lookup needed (ItemUoM never holds a
    row for the item's own base unit — see that model's docstring).
    Any other unit must have a matching ItemUoM row for this exact
    item; a unit nobody ever configured for this item is a real error,
    not a silent 1:1 assumption."""
    if uom is None or uom_id_matches_base(item, uom):
        return qty
    try:
        factor = ItemUoM.objects.get(item=item, uom=uom, deleted_at__isnull=True).factor_to_base
    except ItemUoM.DoesNotExist:
        raise ValidationError(
            _("%(uom)s is not a configured unit for item %(item)s.") % {"uom": uom, "item": item}
        )
    return (qty * factor).normalize() if isinstance(qty, Decimal) else qty * factor


def uom_id_matches_base(item, uom):
    return item.base_uom_id is not None and item.base_uom_id == uom.id


def is_batch_expired(batch, as_of=None):
    """Sprint 7.2.5 (D11): "دفعة منتهية لا تُصرف ولا تُباع" — a plain
    date comparison, no cost involved. `as_of` defaults to today;
    sprint 7.3/7.9 pass a document's own posting date explicitly
    rather than relying on this function's own default, since a
    backdated document must be judged against ITS date, not today's."""
    if batch.expiry is None:
        return False
    from django.utils import timezone

    as_of = as_of or timezone.localdate()
    return batch.expiry < as_of


def select_fefo_batch(item, warehouse, qty_needed, as_of=None):
    """Sprint 7.2.5 (D11): FEFO is a CONSUMPTION-ORDER rule, not a
    pricing rule — it decides WHICH batch's quantity gets reduced
    first (first-expiry-first-out: the batch expiring soonest among
    those with stock in this warehouse, excluding any already-expired
    batch — see is_batch_expired above), never how much that
    consumption is WORTH. Cost is a separate, unrelated question
    answered exclusively by apps.inventory.models.ItemCost's own
    moving weighted average (D2) — picking batch A over batch B here
    changes nothing about the unit cost a withdrawal is valued at.
    Callers needing a specific batch instead of the automatic pick
    (the decision's own "مع إمكانية الاختيار اليدوي") simply skip this
    function and pass their own chosen batch straight through.

    Returns the single BatchStock row FEFO would consume from next
    (the caller decides how much of `qty_needed` that row can actually
    cover — this function does not split across multiple batches),
    or None if no non-expired batch has any stock in this warehouse.
    `qty_needed` is accepted for interface symmetry with future
    multi-batch splitting (sprint 7.3) but unused by this first,
    single-batch-pick version — never silently ignored without
    saying so here.

    Ordering is explicit, not left to the database's own default: a
    bare `.order_by("batch__expiry")` happens to put NULL (no-expiry)
    batches last on PostgreSQL (NULLS LAST is its own ASC default),
    which IS the correct FEFO behavior — but SQLite and MySQL both
    treat NULL as the smallest value (NULLS FIRST), which would flip
    this silently to consuming undated batches before dated ones on
    either engine, a real stock-valuation bug with no red test to
    catch it. `nulls_last=True` makes the intended behavior the
    actual query, not an accident of which database happens to be
    running. A second ordering key (`created_at`) breaks ties between
    two batches sharing the exact same expiry date deterministically
    — otherwise that tie is unordered, and which one gets consumed
    would vary run to run, the same "wait for a signal/declared order,
    not whatever happens to come back" rule e2e tests were just fixed
    under."""
    del qty_needed  # unused for now — see docstring
    candidates = (
        BatchStock.objects.filter(batch__item=item, warehouse=warehouse, qty__gt=0)
        .select_related("batch")
        .order_by(F("batch__expiry").asc(nulls_last=True), "batch__created_at")
    )
    for candidate in candidates:
        if not is_batch_expired(candidate.batch, as_of=as_of):
            return candidate
    return None




# ---------------------------------------------------------------------------
# Sprint 7.3: the stock posting engine.
#
# One entry point per business action (post_stock_document,
# reverse_stock_document, confirm_transfer_receipt), all funnelling into
# _run_moves, which owns the fixed order the block spec names:
# lock -> date rule -> availability -> cost -> StockMove rows -> running
# balances -> journal entry (linked to the document through its
# content_type/object_id). assert_open_period runs first, in each entry
# point, before anything is locked.
#
# Cost model (D2): ItemCost is per (item, COMPANY entity) — every branch
# under one company shares one moving weighted average; quantities for
# availability are per warehouse (StockLevel). ItemCost.total_value is
# the authoritative number; avg_cost (and StockMove.unit_cost) are kept
# to 4 places (UNIT_COST_DECIMAL_PLACES). An outflow is valued at
# total_value/qty at full precision, never at the stored average — EXCEPT
# when the company quantity is already <= 0 (only reachable under
# InventorySettings.allow_negative_stock): total_value/qty is meaningless
# there, so the outflow is valued at the stored 4-place avg_cost
# (_apply_cost: the `else` that follows `elif old_qty > 0`).
# ---------------------------------------------------------------------------

_ZERO = Decimal("0")
_CENTS = Decimal("0.01")
_UNIT = Decimal("0.0001")


def _money(amount):
    return amount.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _unit_cost(amount):
    return amount.quantize(_UNIT, rounding=ROUND_HALF_UP)


def _fmt_qty(qty):
    """8.00 -> "8", 2.50 -> "2.5" — for the Arabic messages only."""
    text = format(qty.normalize(), "f")
    return text


@dataclass
class _PlannedMove:
    line: StockDocumentLine
    item: object
    warehouse: Warehouse
    qty: Decimal  # signed: + into `warehouse`, - out of it
    # Magnitude of the value this move carries when it is fixed in
    # advance (a receipt's qty x unit_cost, a reversal's original value,
    # a transfer's in-transit value). None = "value it at the running
    # average at posting time" (only ever an outflow).
    fixed_value: Decimal | None
    counter_account: object
    batch: Batch | None = None
    serial_ids: list = field(default_factory=list)
    from_transit: bool = False  # inflow whose serials must be IN_TRANSIT
    to_transit: bool = False  # outflow whose serials become IN_TRANSIT
    check_expiry: bool = False
    # Filled by _run_moves:
    value: Decimal = _ZERO  # signed inventory movement
    unit_cost: Decimal = _ZERO
    counter_value: Decimal = _ZERO
    adjustment: Decimal = _ZERO  # debit (+) / credit (-) to INVENTORY_ADJUSTMENT


def _inventory_account(tenant, item, warehouse, document_override=None):
    """INVENTORY role — document override -> warehouse -> item -> category
    -> INVENTORY system account.

    Location first: stock physically sits in a warehouse, so a warehouse-
    level inventory account must win over an item's; if the item override
    came first, Warehouse.inventory_account_override would be unreachable
    for any item that has one. (Owner decision 2026-10-13.)

    `document_override`: StockDocument carries no inventory-account field
    today (its `account` is the COUNTER account — it replaces GRNI on a
    receipt and COGS on an issue), so every caller passes None; the slot
    exists so the order is fixed before such a field is ever added."""
    category = item.category
    return (
        document_override
        or warehouse.inventory_account_override
        or item.inventory_account_override
        or (category.default_inventory_account if category else None)
        or get_required_system_account(tenant, "INVENTORY")
    )


def _cogs_account(tenant, item, warehouse, document_override=None):
    """COGS role — document override -> item -> category -> warehouse ->
    COGS system account.

    Product first, the opposite of _inventory_account: cost of sales is
    analysed by product line, not by location, so an item/category COGS
    account must win over the warehouse's. (Owner decision 2026-10-13.)"""
    category = item.category
    return (
        document_override
        or item.cogs_account_override
        or (category.default_cogs_account if category else None)
        or warehouse.cogs_account_override
        or get_required_system_account(tenant, "COGS")
    )


def _adjustment_account(tenant, item, warehouse, document_override=None):
    """INVENTORY_ADJUSTMENT role — same product-first order as COGS:
    document override -> item -> category -> warehouse -> system account.
    Product and ItemCategory have no adjustment-account field yet, so in
    practice this is warehouse -> system; the order is fixed now so those
    fields slot in without re-deciding it. Callers pass no document
    override for the RECEIPT/ISSUE/TRANSFER kinds: their document.account
    plays the GRNI/COGS role, and routing a rounding residue to a
    supplier or expense account chosen for a different purpose would be
    wrong (a COUNT document's account would be a genuine override here)."""
    del item  # no item/category adjustment field exists yet — see docstring
    return (
        document_override
        or warehouse.adjustment_account_override
        or get_required_system_account(tenant, "INVENTORY_ADJUSTMENT")
    )


def _validate_lines(document, lines):
    from apps.sales.models import Product

    if not lines:
        raise ValidationError("لا يمكن ترحيل مستند مخزني بلا سطور.")
    for line in lines:
        item = line.item
        if item.item_type != Product.ItemType.STOCK:
            raise ValidationError(f"الصنف «{item.name}» صنف خدمي ولا يدخل المخزون.")
        if line.qty_base == 0:
            raise ValidationError(f"كمية الصنف «{item.name}» صفر — لا حركة بكمية صفرية.")
        if item.tracking == InventorySettings.Tracking.BATCH and line.batch_id is None:
            raise ValidationError(f"الصنف «{item.name}» متتبَّع بالدفعات — حدِّد الدفعة.")
        if line.batch_id is not None and line.batch.item_id != item.id:
            raise ValidationError(f"الدفعة «{line.batch.number}» لا تخص الصنف «{item.name}».")
        if item.tracking == InventorySettings.Tracking.SERIAL:
            count = len(line.serial_ids)
            if Decimal(count) != abs(line.qty_base):
                raise ValidationError(
                    f"الصنف «{item.name}» متتبَّع بالسيريال: الكمية {_fmt_qty(abs(line.qty_base))} "
                    f"وعدد السيريالات {count}."
                )


def _load_lines(document):
    lines = list(
        document.lines.select_related("item", "item__category", "batch").order_by("id")
    )
    serials = {}
    through = StockDocumentLine.serials.through
    for line_id, serial_id in through.objects.filter(stockdocumentline__document=document).values_list(
        "stockdocumentline_id", "serialnumber_id"
    ):
        serials.setdefault(line_id, []).append(serial_id)
    for line in lines:
        line.serial_ids = sorted(serials.get(line.id, []))
    return lines


def _plan_document_moves(document, lines, value_overrides):
    """RECEIPT/ISSUE/TRANSFER only. A reversal document carries the
    same kind with negated quantities (reverse_stock_document), so the
    direction is kind-sign x line-sign; its values come in fixed through
    `value_overrides` (the original moves' own values)."""
    tenant = document.tenant
    kind = document.kind
    Kind = StockDocument.Kind
    if kind not in (Kind.RECEIPT, Kind.ISSUE, Kind.TRANSFER):
        raise ValidationError(f"ترحيل مستند من نوع «{document.get_kind_display()}» غير مدعوم في هذا المحرك بعد.")

    warehouse = document.warehouse
    if kind == Kind.TRANSFER:
        if document.to_warehouse_id is None or document.to_warehouse_id == document.warehouse_id:
            raise ValidationError("التحويل يحتاج مستودع وجهة مختلفًا عن مستودع المصدر.")
        if company_entity_for(document.to_warehouse.legal_entity).id != company_entity_for(warehouse.legal_entity).id:
            raise ValidationError("التحويل بين شركتين مختلفتين غير مدعوم — التحويل بين فروع الشركة نفسها فقط.")

    moves = []
    for line in lines:
        direction = 1 if kind == Kind.RECEIPT else -1
        qty = line.qty_base * direction
        fixed = value_overrides.get(line.id)
        if kind == Kind.RECEIPT:
            counter = document.account or get_required_system_account(tenant, "GRNI")
        elif kind == Kind.ISSUE:
            counter = _cogs_account(tenant, line.item, warehouse, document_override=document.account)
        else:
            counter = get_required_system_account(tenant, "GOODS_IN_TRANSIT")
        if qty > 0 and fixed is None:
            fixed = _money(qty * line.unit_cost)
        moves.append(
            _PlannedMove(
                line=line, item=line.item, warehouse=warehouse, qty=qty, fixed_value=fixed,
                counter_account=counter, batch=line.batch, serial_ids=line.serial_ids,
                from_transit=(kind == Kind.TRANSFER and qty > 0),
                to_transit=(kind == Kind.TRANSFER and qty < 0),
                check_expiry=(kind == Kind.ISSUE and qty < 0),
            )
        )
    return moves


def _lock_balances(tenant, company, moves):
    """Creates any missing ItemCost/StockLevel/BatchStock row (INSERT ..
    ON CONFLICT DO NOTHING — safe against a concurrent creator), then
    takes FOR UPDATE row locks on every balance row this posting will
    read, in a fixed order (item, warehouse, batch ids) so two postings
    over overlapping items can never deadlock each other. Everything the
    caller reads afterwards — the date rule, availability, the running
    average — is read under these locks."""
    item_ids = sorted({m.item.id for m in moves})
    level_keys = sorted({(m.item.id, m.warehouse.id) for m in moves})
    batch_keys = sorted({(m.batch.id, m.warehouse.id) for m in moves if m.batch is not None})

    ItemCost.objects.bulk_create(
        [ItemCost(tenant=tenant, item_id=item_id, company_entity=company) for item_id in item_ids],
        ignore_conflicts=True,
    )
    StockLevel.objects.bulk_create(
        [StockLevel(tenant=tenant, item_id=i, warehouse_id=w) for i, w in level_keys], ignore_conflicts=True
    )
    if batch_keys:
        BatchStock.objects.bulk_create(
            [BatchStock(tenant=tenant, batch_id=b, warehouse_id=w) for b, w in batch_keys], ignore_conflicts=True
        )

    costs = {
        c.item_id: c
        for c in ItemCost.objects.select_for_update()
        .filter(tenant=tenant, company_entity=company, item_id__in=item_ids)
        .order_by("item_id")
    }
    level_filter = Q()
    for item_id, warehouse_id in level_keys:
        level_filter |= Q(item_id=item_id, warehouse_id=warehouse_id)
    levels = {
        (lvl.item_id, lvl.warehouse_id): lvl
        for lvl in StockLevel.objects.select_for_update().filter(level_filter).order_by("item_id", "warehouse_id")
    }
    batch_levels = {}
    if batch_keys:
        batch_filter = Q()
        for batch_id, warehouse_id in batch_keys:
            batch_filter |= Q(batch_id=batch_id, warehouse_id=warehouse_id)
        batch_levels = {
            (bs.batch_id, bs.warehouse_id): bs
            for bs in BatchStock.objects.select_for_update().filter(batch_filter).order_by("batch_id", "warehouse_id")
        }
    return costs, levels, batch_levels


def _check_date(company, moves, on_date):
    """"يُرفض الترحيل بتاريخ أقدم من آخر حركة للصنف في الشركة" — one
    aggregate query over every item on the document."""
    item_names = {m.item.id: m.item.name for m in moves}
    late = (
        StockMove.objects.filter(company_entity=company, item_id__in=item_names)
        .values("item_id")
        .annotate(last_date=Max("date"))
        .filter(last_date__gt=on_date)
        .order_by("item_id")
        .first()
    )
    if late:
        raise ValidationError(
            f"لا يمكن الترحيل بتاريخ {on_date}: آخر حركة للصنف «{item_names[late['item_id']]}» "
            f"في الشركة بتاريخ {late['last_date']} — لا ترحيل بتاريخ أقدم من آخر حركة."
        )


def _check_availability(tenant, moves, levels, batch_levels, on_date):
    allow_negative = InventorySettings.objects.filter(tenant=tenant, allow_negative_stock=True).exists()

    needed = {}
    batch_needed = {}
    for m in moves:
        if m.qty >= 0:
            continue
        key = (m.item.id, m.warehouse.id)
        needed[key] = needed.get(key, _ZERO) - m.qty
        if m.batch is not None:
            bkey = (m.batch.id, m.warehouse.id)
            batch_needed[bkey] = batch_needed.get(bkey, _ZERO) - m.qty
        if m.check_expiry and m.batch is not None and is_batch_expired(m.batch, as_of=on_date):
            raise ValidationError(
                f"الدفعة «{m.batch.number}» من الصنف «{m.item.name}» منتهية الصلاحية ({m.batch.expiry}) — لا تُصرف."
            )

    if not allow_negative:
        by_key = {(m.item.id, m.warehouse.id): m for m in moves}
        for key, qty in needed.items():
            level = levels[key]
            available = level.qty_on_hand - level.qty_reserved
            if qty > available:
                m = by_key[key]
                raise ValidationError(
                    f"الكمية المتاحة من الصنف «{m.item.name}» في المستودع «{m.warehouse.name}» "
                    f"هي {_fmt_qty(available)} فقط، والمطلوب {_fmt_qty(qty)}."
                )
        by_bkey = {(m.batch.id, m.warehouse.id): m for m in moves if m.batch is not None}
        for bkey, qty in batch_needed.items():
            available = batch_levels[bkey].qty
            if qty > available:
                m = by_bkey[bkey]
                raise ValidationError(
                    f"الكمية المتاحة من الدفعة «{m.batch.number}» للصنف «{m.item.name}» في المستودع "
                    f"«{m.warehouse.name}» هي {_fmt_qty(available)} فقط، والمطلوب {_fmt_qty(qty)}."
                )

    # Serials are never "negative stock" — a physical serial is either
    # where the document says it is, or it isn't.
    Status = SerialNumber.Status
    for m in moves:
        if not m.serial_ids:
            continue
        serials = SerialNumber.objects.select_for_update().filter(id__in=m.serial_ids, item=m.item).order_by("id")
        if m.qty < 0:
            ok = Q(status=Status.IN_STOCK, warehouse=m.warehouse)
            where = f"في المستودع «{m.warehouse.name}»"
        elif m.from_transit:
            ok = Q(status=Status.IN_TRANSIT)
            where = "في الطريق"
        else:
            ok = ~Q(status__in=[Status.IN_STOCK, Status.IN_TRANSIT]) | Q(status=Status.IN_STOCK, warehouse__isnull=True)
            where = "خارج المخزون"
        found = list(serials)
        bad = [s.serial for s in serials.exclude(ok)]
        if len(found) != len(m.serial_ids) or bad:
            raise ValidationError(
                f"السيريال {', '.join(bad) or '؟'} للصنف «{m.item.name}» ليس {where}."
            )


def _apply_cost(cost, m):
    """The moving weighted average, one move at a time. Returns nothing;
    fills m.value/unit_cost/counter_value/adjustment and mutates `cost`
    in place. Rounding residue rule: once the company-wide quantity
    reaches zero the value is zero exactly, and the residue is booked
    (to the counter account for an at-average outflow, to
    INVENTORY_ADJUSTMENT when the outflow's value was fixed in advance)."""
    old_qty, old_value = cost.qty_on_hand, cost.total_value
    new_qty = old_qty + m.qty
    if m.qty > 0:
        counter = m.fixed_value
        new_value = old_value + counter
    else:
        out_qty = -m.qty
        if m.fixed_value is not None:
            counter = m.fixed_value
        elif new_qty == 0:
            counter = old_value
        elif old_qty > 0:
            counter = _money(out_qty * old_value / old_qty)
        else:
            counter = _money(out_qty * cost.avg_cost)
        new_value = old_value - counter
    if new_qty == 0:
        new_value = _ZERO
    delta = new_value - old_value

    m.value = delta
    m.counter_value = counter
    # Debit-positive balancing amount: inflow Dr inventory delta /
    # Cr counter; outflow Dr counter / Cr inventory -delta.
    m.adjustment = (counter - delta) if m.qty > 0 else (-delta - counter)
    m.unit_cost = _unit_cost(counter / abs(m.qty))

    cost.qty_on_hand = new_qty
    cost.total_value = new_value
    if new_qty > 0:
        cost.avg_cost = _unit_cost(new_value / new_qty)


def _post_journal_entry(document, legal_entity, on_date, memo, moves, user):
    """Builds one balanced entry from the moves (netted per account and
    cost center), creates it APPROVED and posts it through
    apps.accounting.services.post_journal_entry — the existing posting
    path (lock, period gate, audit log), not a second one. Linked to the
    StockDocument by content_type/object_id, which is exactly what
    reverse_journal_entry's own stock-document guard keys on."""
    tenant = document.tenant
    buckets = {}

    def add(account, cost_center, amount):
        if amount:
            key = (account.id, cost_center.id if cost_center else None)
            account_and_cc, total = buckets.get(key, ((account, cost_center), _ZERO))
            buckets[key] = (account_and_cc, total + amount)

    for m in moves:
        cost_center = m.line.cost_center or m.warehouse.cost_center
        add(_inventory_account(tenant, m.item, m.warehouse), cost_center, m.value)
        add(m.counter_account, cost_center, m.counter_value if m.qty < 0 else -m.counter_value)
        if m.adjustment:
            add(_adjustment_account(tenant, m.item, m.warehouse), cost_center, m.adjustment)

    specs = [
        {
            "account": account,
            "cost_center": cost_center,
            "debit_fc": total if total > 0 else _ZERO,
            "credit_fc": -total if total < 0 else _ZERO,
        }
        for (account, cost_center), total in buckets.values()
        if total
    ]
    if not specs:
        return None

    entry = JournalEntry.objects.create(
        tenant=tenant,
        legal_entity=legal_entity,
        date=on_date,
        memo=memo,
        number=next_document_number(tenant, "journal_entry", legal_entity, on_date),
        status=JournalEntry.Status.APPROVED,
        created_by=user,
        produced_by=JournalEntry.ProducedBy.STOCK_DOCUMENT,
        content_type=ContentType.objects.get_for_model(StockDocument),
        object_id=document.id,
        currency=legal_entity.base_currency,
        exchange_rate=Decimal("1"),
    )
    JournalLine.objects.bulk_create(build_journal_lines_with_fx_rounding(tenant, entry, specs, Decimal("1")))
    post_journal_entry(entry, user)
    return entry


def _run_moves(document, moves, on_date):
    tenant = document.tenant
    company = company_entity_for(moves[0].warehouse.legal_entity)

    # 1. Locks first — see _lock_balances. Taken BEFORE the date rule,
    # the availability check and the cost read, so none of the three can
    # be invalidated by a concurrent posting between the read and the write.
    costs, levels, batch_levels = _lock_balances(tenant, company, moves)
    # 2. Date rule.
    _check_date(company, moves, on_date)
    # 3. Availability (warehouse, batch, serial).
    _check_availability(tenant, moves, levels, batch_levels, on_date)
    # 4. Cost — read from the locked ItemCost rows.
    for m in moves:
        _apply_cost(costs[m.item.id], m)

    # 5. StockMove rows.
    StockMove.objects.bulk_create(
        [
            StockMove(
                tenant=tenant, document=document, line=m.line, item=m.item, warehouse=m.warehouse,
                legal_entity=m.warehouse.legal_entity, company_entity=company, date=on_date,
                qty_base=m.qty, unit_cost=m.unit_cost, value=m.value, batch=m.batch,
                serial_id=m.serial_ids[0] if len(m.serial_ids) == 1 else None,
            )
            for m in moves
        ]
    )

    # 6. Running balances.
    now = timezone.now()
    for m in moves:
        levels[(m.item.id, m.warehouse.id)].qty_on_hand += m.qty
        levels[(m.item.id, m.warehouse.id)].updated_at = now
        if m.batch is not None:
            batch_levels[(m.batch.id, m.warehouse.id)].qty += m.qty
            batch_levels[(m.batch.id, m.warehouse.id)].updated_at = now
    for cost in costs.values():
        cost.updated_at = now
    StockLevel.objects.bulk_update(levels.values(), ["qty_on_hand", "updated_at"])
    if batch_levels:
        BatchStock.objects.bulk_update(batch_levels.values(), ["qty", "updated_at"])
    ItemCost.objects.bulk_update(costs.values(), ["qty_on_hand", "total_value", "avg_cost", "updated_at"])
    _move_serials(document, moves)
    # 7. The journal entry is the caller's next step (_post_journal_entry)
    # — after it has assigned the document number the memo names.


def _move_serials(document, moves):
    Status = SerialNumber.Status
    for m in moves:
        if not m.serial_ids:
            continue
        serials = SerialNumber.objects.filter(id__in=m.serial_ids)
        if m.qty > 0:
            serials.update(
                status=Status.IN_STOCK, warehouse=m.warehouse, batch=m.batch or F("batch"),
                received_doc=document.id,
            )
        elif m.to_transit:
            serials.update(status=Status.IN_TRANSIT, warehouse=None)
        else:
            serials.update(status=Status.ISSUED, warehouse=None, issued_doc=document.id)


def _post_document(document, user, value_overrides):
    """Shared by post_stock_document and reverse_stock_document: the
    document must still be pre-POSTED (its lines are still writable
    under 0006's trigger) — issue lines get their posting-time unit_cost
    recorded on the line before the status flip."""
    from apps.accounting.periods import assert_open_period

    assert_open_period(document.tenant, document.date)
    lines = _load_lines(document)
    _validate_lines(document, lines)
    moves = _plan_document_moves(document, lines, value_overrides)
    _run_moves(document, moves, document.date)

    changed = []
    for m in moves:
        # The line keeps a 2-place, human-scale price (PRICE_DECIMAL_PLACES);
        # the exact 4-place cost lives on the StockMove.
        line_cost = _money(m.unit_cost)
        if m.line.unit_cost != line_cost:
            m.line.unit_cost = line_cost
            changed.append(m.line)
    if changed:
        StockDocumentLine.objects.bulk_update(changed, ["unit_cost"])

    if not document.number:
        document.number = next_document_number(
            document.tenant, f"stock_{document.kind}", document.legal_entity, document.date
        )
    entry = _post_journal_entry(
        document, document.legal_entity, document.date,
        f"{document.get_kind_display()} {document.number}", moves, user,
    )
    document.status = StockDocument.Status.POSTED
    document.save(update_fields=["number", "status"])
    return entry


@transaction.atomic
def post_stock_document(document, user, request=None):
    """Sprint 7.3: the real posting engine on top of 7.2.6's numbering/
    status skeleton — see _run_moves for the order of operations."""
    document.status = StockDocument.objects.select_for_update().get(pk=document.pk).status
    if document.status != StockDocument.Status.APPROVED:
        raise ValidationError(_("Only an approved stock document can be posted."))
    _post_document(document, user, value_overrides={})
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER,
        actor_id=user.id,
        action="stock_document.posted",
        target_type="stock_document",
        target_id=document.id,
        tenant_id=document.tenant_id,
        request=request,
    )
    return document


def _transfer_received(document):
    return StockMove.objects.filter(document=document, warehouse_id=document.to_warehouse_id, qty_base__gt=0).exists()


@transaction.atomic
def confirm_transfer_receipt(document, user, date=None, request=None):
    """Sprint 7.3: second half of a TRANSFER. Posting the transfer moved
    the goods out of the source warehouse into GOODS_IN_TRANSIT (Dr GIT /
    Cr inventory, on the document's own entity); confirming moves them
    into `to_warehouse` at exactly the value that left (Dr inventory /
    Cr GIT, on the destination warehouse's entity), so GIT returns to
    zero and — both branches sharing one company ItemCost — the average
    comes back to where it was absent any other movement in between."""
    from apps.accounting.periods import assert_open_period

    document.status = StockDocument.objects.select_for_update().get(pk=document.pk).status
    if document.kind != StockDocument.Kind.TRANSFER or document.reverses_id is not None:
        raise ValidationError("تأكيد الاستلام لمستند تحويل أصلي فقط.")
    if document.status != StockDocument.Status.POSTED:
        raise ValidationError("لا يُؤكَّد استلام تحويل غير مرحَّل (أو معكوس).")
    if _transfer_received(document):
        raise ValidationError("تم تأكيد استلام هذا التحويل من قبل.")
    on_date = date or timezone.localdate()
    if on_date < document.date:
        raise ValidationError("تاريخ الاستلام لا يسبق تاريخ التحويل.")
    assert_open_period(document.tenant, on_date)

    to_warehouse = document.to_warehouse
    git = get_required_system_account(document.tenant, "GOODS_IN_TRANSIT")
    lines = {line.id: line for line in _load_lines(document)}
    moves = [
        _PlannedMove(
            line=lines[out.line_id], item=out.item, warehouse=to_warehouse, qty=-out.qty_base,
            fixed_value=-out.value, counter_account=git, batch=out.batch,
            serial_ids=lines[out.line_id].serial_ids, from_transit=True,
        )
        for out in document.moves.filter(warehouse_id=document.warehouse_id)
        .select_related("item", "item__category", "batch")
        .order_by("line_id")
    ]
    _run_moves(document, moves, on_date)
    _post_journal_entry(
        document, to_warehouse.legal_entity, on_date, f"استلام تحويل {document.number}", moves, user
    )
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER,
        actor_id=user.id,
        action="stock_document.transfer_received",
        target_type="stock_document",
        target_id=document.id,
        tenant_id=document.tenant_id,
        after={"date": str(on_date)},
        request=request,
    )
    return document


@transaction.atomic
def reverse_stock_document(document, user, reason, request=None, date=None):
    """"التصحيح بمستند معاكس" — a new, linked document with every
    line's quantity negated, posted through the same engine, never a
    direct edit of the posted document (0006's trigger forbids that
    anyway). Each reversed line moves back exactly the inventory value
    its original line moved (the original StockMove.value), not a value
    re-derived from today's average — so reversing the latest movement
    restores quantity, value and average exactly.

    A TRANSFER whose receipt was already confirmed is not reversible
    here (its goods now sit in the destination warehouse) — the
    correction is a new transfer back.

    `original_lines`/`reversed_lines` are paired by construction order
    (bulk_create's own return value), never by a second `.all()` query
    — two separate queries are not guaranteed to agree on order (the
    exact class of bug 7.2.5's own FEFO review caught: don't rely on
    an undeclared order)."""
    document.status = StockDocument.objects.select_for_update().get(pk=document.pk).status
    if document.status != StockDocument.Status.POSTED:
        raise ValidationError(_("Only a posted stock document can be reversed."))
    if not reason:
        raise ValidationError(_("A reason is required to reverse a stock document."))
    if document.kind == StockDocument.Kind.TRANSFER and _transfer_received(document):
        raise ValidationError("تم استلام هذا التحويل — التصحيح بتحويل معاكس من مستودع الوجهة، لا بعكس المستند.")

    reversal_date = date or timezone.localdate()
    reversal = StockDocument.objects.create(
        tenant=document.tenant,
        legal_entity=document.legal_entity,
        warehouse=document.warehouse,
        to_warehouse=document.to_warehouse,
        kind=document.kind,
        date=reversal_date,
        party=document.party,
        account=document.account,
        reference=document.reference,
        notes=_("Reversal of %(number)s: %(reason)s") % {"number": document.number or document.id, "reason": reason},
        reverses=document,
        created_by=user,
        status=StockDocument.Status.DRAFT,
    )
    # Lines are built while the reversal is still DRAFT — the trigger's
    # own INSERT branch (0006) rejects a line bulk_created onto an
    # already-POSTED document.
    original_lines = list(document.lines.order_by("id"))
    reversed_lines = StockDocumentLine.objects.bulk_create(
        [
            StockDocumentLine(
                document=reversal,
                item=line.item,
                uom=line.uom,
                qty=-line.qty,
                qty_base=-line.qty_base,
                unit_cost=line.unit_cost,
                cost_center=line.cost_center,
                batch=line.batch,
                expected_qty=line.expected_qty,
                counted_qty=line.counted_qty,
            )
            for line in original_lines
        ]
    )
    original_values = dict(
        StockMove.objects.filter(document=document, warehouse_id=document.warehouse_id).values_list("line_id", "value")
    )
    value_overrides = {}
    for original_line, reversed_line in zip(original_lines, reversed_lines):
        serial_ids = list(original_line.serials.values_list("id", flat=True))
        if serial_ids:
            reversed_line.serials.set(serial_ids)
        value_overrides[reversed_line.id] = abs(original_values[original_line.id])

    _post_document(reversal, user, value_overrides)

    document.status = StockDocument.Status.REVERSED
    document.save(update_fields=["status"])

    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER,
        actor_id=user.id,
        action="stock_document.reversed",
        target_type="stock_document",
        target_id=document.id,
        tenant_id=document.tenant_id,
        after={"reason": reason, "reversal_id": str(reversal.id)},
        request=request,
    )
    return reversal
