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
    # Sprint 7.5: a COUNT variance — an outflow's serials become DISPOSED
    # (not ISSUED), and a reversal's inflow brings them back IN_STOCK.
    count: bool = False
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


def _count_line_balance(line, levels, batch_levels, warehouse):
    if line.batch_id is not None:
        return batch_levels[(line.batch_id, warehouse.id)].qty
    return levels[(line.item_id, warehouse.id)].qty_on_hand


def zero_cost_surplus_message(items, approved=False):
    """`items`: [(item, surplus qty)] — every surplus line whose item has a
    zero company average and no unit cost entered. `approved`: the session
    passed approval without this (the balance moved since) — entering the
    cost now voids that approval, and the message says so. One item or
    several, both branches agree in number."""
    one = len(items) == 1
    names = "، ".join(f"«{item.name}» ({item.sku}) بزيادة {_fmt_qty(qty)}" for item, qty in items)
    if approved:
        return (
            f"{'هذا السطر صار' if one else 'هذه الأسطر صارت'} زيادة بمتوسط صفر بعد تغيّر الرصيد ({names}). "
            "أدخل تكلفة الوحدة في تبويب الفروق — سيعود المستند إلى مسودة ويحتاج اعتمادًا جديدًا."
        )
    return (
        f"لا تُثبت زيادة جرد بقيمة صفر: {'الصنف' if one else 'الأصناف'} {names} "
        f"{'متوسط تكلفته' if one else 'متوسط تكلفتها'} في الشركة صفر. "
        "أدخل تكلفة وحدة الزيادة في تبويب الفروق، أو أدخل الزيادة بإذن إضافة من «أذون الإضافة»."
    )


def _plan_count_moves(document, lines, value_overrides):
    """Sprint 7.5 (D16): a COUNT's moves.

    A count session never moves what nobody counted: a line whose
    counted_qty is NULL produces nothing, and an item outside the session's
    scope has no line at all. Counted-and-zero is a real count (the whole
    balance goes); not-counted is no information.

    The variance is computed HERE, at posting, under the same row locks the
    engine then takes: counted − the balance NOW, not counted − the snapshot
    taken when the session opened. Whatever moved in between, the balance
    after posting equals what was counted. (The API shows that drift and
    asks for confirmation before it gets here — count_variances.)

    The variance's quantity is written onto the line (qty/qty_base) and,
    for a serial item, the missing serials onto line.serials — so the
    posted line says exactly what moved, and reverse_stock_document needs
    nothing count-specific to undo it.

    A reversal (document.reverses set) carries the negated quantities and
    the original values (value_overrides), like every other kind."""
    tenant = document.tenant
    warehouse = document.warehouse
    adjustment = _adjustment_account(tenant, None, warehouse, document_override=document.account)

    if document.reverses_id is not None:
        return [
            _PlannedMove(
                line=line, item=line.item, warehouse=warehouse, qty=line.qty_base,
                fixed_value=value_overrides.get(line.id), counter_account=adjustment, batch=line.batch,
                serial_ids=line.serial_ids, count=True,
            )
            for line in lines
            if line.qty_base
        ]

    counted = [line for line in lines if line.counted_qty is not None]
    if not counted:
        raise ValidationError("لم يُدخَل عدّ لأي سطر في جلسة الجرد — لا شيء يُرحَّل.")
    company = company_entity_for(warehouse.legal_entity)
    stubs = [
        _PlannedMove(line=line, item=line.item, warehouse=warehouse, qty=_ZERO, fixed_value=None,
                     counter_account=adjustment, batch=line.batch)
        for line in counted
    ]
    costs, levels, batch_levels = _lock_balances(tenant, company, stubs)

    counted_serials = {}
    through = StockDocumentLine.counted_serials.through
    for line_id, serial_id in through.objects.filter(stockdocumentline__document=document).values_list(
        "stockdocumentline_id", "serialnumber_id"
    ):
        counted_serials.setdefault(line_id, set()).add(serial_id)

    moves, zero_cost = [], []
    for line in counted:
        balance = _count_line_balance(line, levels, batch_levels, warehouse)
        variance = line.counted_qty - balance
        missing = []
        if line.item.tracking == InventorySettings.Tracking.SERIAL:
            in_stock = set(
                SerialNumber.objects.select_for_update()
                .filter(item=line.item, warehouse=warehouse, status=SerialNumber.Status.IN_STOCK)
                .values_list("id", flat=True)
            )
            scanned = counted_serials.get(line.id, set())
            gone = SerialNumber.objects.filter(id__in=scanned - in_stock).order_by("serial")
            if gone:
                raise ValidationError(
                    f"السيريال {', '.join(s.serial for s in gone)} للصنف «{line.item.name}» عُدَّ في الجرد "
                    f"لكنه لم يعد في المستودع «{warehouse.name}»."
                )
            missing = sorted(in_stock - scanned)
            if Decimal(len(missing)) != -variance:
                raise ValidationError(
                    f"الصنف «{line.item.name}»: رصيده {_fmt_qty(balance)} وسيريالاته في المستودع {len(in_stock)} "
                    "— لا يتطابقان، فلا يُحسب فرق السيريالات. صحّح الرصيد قبل الجرد."
                )
        line.qty = line.qty_base = variance
        if not variance:
            continue
        # A surplus enters at the unit cost entered on the variance tab, or
        # else at the company average read under the lock — never at zero:
        # an item whose average is zero (never received at a cost) needs
        # the cost entered, or the surplus goes in on a receipt instead.
        fixed = None
        if variance > 0:
            if line.surplus_unit_cost is not None:
                fixed = _money(variance * line.surplus_unit_cost)
            elif not costs[line.item_id].avg_cost:
                zero_cost.append((line.item, variance))
                continue
        moves.append(
            _PlannedMove(
                line=line, item=line.item, warehouse=warehouse, qty=variance, fixed_value=fixed,
                counter_account=adjustment, batch=line.batch, serial_ids=missing, count=True,
            )
        )
    if zero_cost:
        raise ValidationError(
            zero_cost_surplus_message(zero_cost, approved=document.status == StockDocument.Status.APPROVED)
        )
    StockDocumentLine.objects.bulk_update(counted, ["qty", "qty_base"])
    for m in moves:
        if m.serial_ids:
            m.line.serials.set(m.serial_ids)
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
        # A count surplus (fixed_value None) enters at the company average
        # read under the lock — "الفرق بالمتوسط" (D6). Every other inflow
        # carries its value in fixed_value.
        counter = m.fixed_value if m.fixed_value is not None else _money(m.qty * cost.avg_cost)
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


OPEN_COUNT_STATUSES = (
    StockDocument.Status.DRAFT, StockDocument.Status.PENDING_APPROVAL, StockDocument.Status.APPROVED,
)


def open_count_sessions(tenant, warehouse_ids):
    """Count sessions not yet posted (and not deleted) on these warehouses.
    A reversal document of kind COUNT is never a session."""
    return StockDocument.objects.filter(
        tenant=tenant, kind=StockDocument.Kind.COUNT, warehouse_id__in=warehouse_ids,
        status__in=OPEN_COUNT_STATUSES, deleted_at__isnull=True, reverses__isnull=True,
    )


def count_session_label(session):
    scope = f" — {session.count_scope}" if session.count_scope else ""
    return f"«جرد {session.date}{scope}» ({session.get_status_display()})"


def _assert_not_frozen(document, moves):
    """D16 freeze, inside the engine: every entry point (post, reverse,
    confirm receipt — and any Celery task calling them) runs _run_moves,
    so no caller can post around an open count. The session's own posting
    is the one exception."""
    settings_obj = InventorySettings.objects.filter(tenant=document.tenant).first()
    if settings_obj is not None and not settings_obj.freeze_warehouse_during_count:
        return
    warehouses = {m.warehouse.id: m.warehouse for m in moves}
    session = (
        open_count_sessions(document.tenant, list(warehouses)).exclude(pk=document.pk)
        .order_by("created_at").first()
    )
    if session is not None:
        raise ValidationError(
            f"المستودع «{warehouses[session.warehouse_id].name}» مجمَّد بجلسة الجرد {count_session_label(session)} "
            "— لا يُرحَّل عليه أي مستند حتى ترحيل الجرد أو حذفه."
        )


def _run_moves(document, moves, on_date):
    tenant = document.tenant
    company = company_entity_for(moves[0].warehouse.legal_entity)

    # 0. An open count session freezes its warehouse (D16).
    _assert_not_frozen(document, moves)
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
        if m.count and m.qty > 0:
            # Reversing a count: what the count marked disposed comes back
            # where it was counted missing from.
            serials.update(status=Status.IN_STOCK, warehouse=m.warehouse)
        elif m.count:
            serials.update(status=Status.DISPOSED, warehouse=None, issued_doc=document.id)
        elif m.qty > 0:
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
    if document.kind == StockDocument.Kind.COUNT:
        moves = _plan_count_moves(document, lines, value_overrides)
    else:
        _validate_lines(document, lines)
        moves = _plan_document_moves(document, lines, value_overrides)
    if moves:  # a count whose every counted line matched moves nothing
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
    # A count's drift (balance moved since the session opened) is read
    # before posting and kept in the audit entry: the variance was
    # computed on the current balance, and the record says so.
    drift = count_drift(document) if document.kind == StockDocument.Kind.COUNT else []
    _post_document(document, user, value_overrides={})
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER,
        actor_id=user.id,
        action="stock_document.posted",
        target_type="stock_document",
        target_id=document.id,
        tenant_id=document.tenant_id,
        after={"count_drift": [{k: str(v) if v is not None else None for k, v in d.items()} for d in drift]}
        if drift else None,
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
    original_values = dict(
        StockMove.objects.filter(document=document, warehouse_id=document.warehouse_id).values_list("line_id", "value")
    )
    original_lines = list(document.lines.order_by("id"))
    if document.kind == StockDocument.Kind.COUNT:
        # Only the lines that moved — an uncounted or matching line has
        # nothing to undo.
        original_lines = [line for line in original_lines if line.id in original_values]
        if not original_lines:
            raise ValidationError("هذا الجرد لم يُثبت أي فرق — لا شيء يُعكس.")
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


# ---------------------------------------------------------------------------
# Sprint 7.4: the document layer the API sits on — create/edit a DRAFT,
# the approval workflow (the shared apps.approvals engine, same as
# vouchers), and server-side totals. Posting, reversal and transfer receipt
# are the 7.3 engine functions above, called as they are.
# ---------------------------------------------------------------------------


class StockDocumentLocked(Exception):
    """A non-draft document's header/lines can't be edited — the view maps
    this to 409, same status SoftDeleteDocumentViewSetMixin gives a
    non-draft delete. 0006's trigger is the DB-level backstop for a POSTED
    one; this is the API-level refusal for every non-draft state."""


def approval_doc_type(document):
    return f"stock_{document.kind}"


def resolve_stock_lines(tenant, kind, raw_lines):
    """Raw API line dicts -> StockDocumentLine kwargs (+ serial ids). Every
    id is looked up inside `tenant`. Receipt lines may name a new batch
    (number + expiry) or new serials — those rows are created here; issue
    and transfer lines may only reference what already exists. qty_base is
    always computed server-side (convert_qty_to_base), never accepted."""
    from apps.organization.models import CostCenter
    from apps.sales.models import Product

    from .models import UnitOfMeasure

    is_receipt = kind == StockDocument.Kind.RECEIPT
    seen_serials = {}
    resolved = []
    for index, raw in enumerate(raw_lines, start=1):
        item = Product.objects.filter(tenant=tenant, id=raw["item"], deleted_at__isnull=True).first()
        if item is None:
            raise ValidationError(f"السطر {index}: الصنف غير موجود.")
        if item.item_type != Product.ItemType.STOCK:
            raise ValidationError(f"السطر {index}: الصنف «{item.name}» صنف خدمي ولا يدخل المخزون.")
        uom = None
        if raw.get("uom"):
            uom = UnitOfMeasure.objects.filter(tenant=tenant, id=raw["uom"], deleted_at__isnull=True).first()
            if uom is None:
                raise ValidationError(f"السطر {index}: وحدة القياس غير موجودة.")
        qty = raw["qty"]
        qty_base = convert_qty_to_base(item, uom, qty)
        cost_center = None
        if raw.get("cost_center"):
            cost_center = CostCenter.objects.filter(tenant=tenant, id=raw["cost_center"]).first()
            if cost_center is None:
                raise ValidationError(f"السطر {index}: مركز التكلفة غير موجود.")

        batch = None
        if raw.get("batch"):
            batch = Batch.objects.filter(tenant=tenant, id=raw["batch"], item=item).first()
            if batch is None:
                raise ValidationError(f"السطر {index}: الدفعة غير موجودة لهذا الصنف.")
        elif raw.get("batch_number"):
            number = raw["batch_number"].strip()
            batch = Batch.objects.filter(tenant=tenant, item=item, number=number).first()
            if batch is None:
                if not is_receipt:
                    raise ValidationError(f"السطر {index}: الدفعة «{number}» غير مسجَّلة لهذا الصنف.")
                batch = Batch.objects.create(
                    tenant=tenant, item=item, number=number, expiry=raw.get("batch_expiry"),
                )
            elif raw.get("batch_expiry") and batch.expiry != raw["batch_expiry"]:
                raise ValidationError(
                    f"السطر {index}: الدفعة «{number}» مسجَّلة بتاريخ صلاحية {batch.expiry}، لا {raw['batch_expiry']}."
                )

        serial_ids = []
        for text in raw.get("serials") or []:
            serial = text.strip()
            if not serial:
                continue
            key = (item.id, serial)
            if key in seen_serials:
                raise ValidationError(
                    f"السيريال «{serial}» مكرر في المستند (السطر {seen_serials[key]} والسطر {index})."
                )
            seen_serials[key] = index
            row = SerialNumber.objects.filter(tenant=tenant, item=item, serial=serial).first()
            if row is None:
                if not is_receipt:
                    raise ValidationError(f"السطر {index}: السيريال «{serial}» غير مسجَّل للصنف «{item.name}».")
                row = SerialNumber.objects.create(tenant=tenant, item=item, serial=serial, batch=batch)
            serial_ids.append(row.id)

        resolved.append(
            {
                "item": item, "uom": uom, "qty": qty, "qty_base": qty_base,
                # Cost is entered only on a receipt; an issue/transfer's cost
                # is fixed by the engine at posting (moving average).
                "unit_cost": (raw.get("unit_cost") or Decimal("0")) if is_receipt else Decimal("0"),
                "cost_center": cost_center, "batch": batch, "serial_ids": serial_ids,
            }
        )
    return resolved


def _validate_header(tenant, data):
    kind = data["kind"]
    warehouse = data["warehouse"]
    if warehouse.legal_entity_id != data["legal_entity"].id:
        raise ValidationError("المستودع لا يتبع الكيان المختار.")
    if kind == StockDocument.Kind.TRANSFER:
        to_warehouse = data.get("to_warehouse")
        if to_warehouse is None:
            raise ValidationError("التحويل يحتاج مستودع وجهة.")
        if to_warehouse.id == warehouse.id:
            raise ValidationError("مستودع الوجهة يجب أن يختلف عن مستودع المصدر.")
        if company_entity_for(to_warehouse.legal_entity).id != company_entity_for(warehouse.legal_entity).id:
            raise ValidationError("التحويل بين فروع الشركة نفسها فقط.")
    elif data.get("to_warehouse") is not None:
        raise ValidationError("مستودع الوجهة للتحويل فقط.")
    account = data.get("account")
    if account is not None and not account.can_post:
        raise ValidationError(f"لا يمكن الترحيل على الحساب {account.code}.")


def _write_lines(document, resolved_lines):
    lines = StockDocumentLine.objects.bulk_create(
        [
            StockDocumentLine(
                document=document, item=spec["item"], uom=spec["uom"], qty=spec["qty"],
                qty_base=spec["qty_base"], unit_cost=spec["unit_cost"], cost_center=spec["cost_center"],
                batch=spec["batch"],
            )
            for spec in resolved_lines
        ]
    )
    for line, spec in zip(lines, resolved_lines):
        if spec["serial_ids"]:
            line.serials.set(spec["serial_ids"])


_HEADER_FIELDS = ("kind", "legal_entity", "warehouse", "to_warehouse", "date", "party", "account", "reference", "notes")


@transaction.atomic
def create_stock_document(tenant, user, data, raw_lines, request=None):
    """A new DRAFT, header + lines, in one transaction — including any
    batch/serial rows resolve_stock_lines creates, so a rejected document
    leaves none behind."""
    _validate_header(tenant, data)
    resolved_lines = resolve_stock_lines(tenant, data["kind"], raw_lines)
    if not resolved_lines:
        raise ValidationError("المستند يحتاج سطرًا واحدًا على الأقل.")
    document = StockDocument.objects.create(
        tenant=tenant, created_by=user, status=StockDocument.Status.DRAFT,
        **{name: data.get(name) for name in _HEADER_FIELDS if name in data},
    )
    _write_lines(document, resolved_lines)
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER, actor_id=user.id, action="stock_document.created",
        target_type="stock_document", target_id=document.id, tenant_id=tenant.id, request=request,
    )
    return document


@transaction.atomic
def update_stock_document(document, user, data, raw_lines, request=None):
    """Full replace of a DRAFT's header and lines. Anything past DRAFT is
    refused (StockDocumentLocked -> 409), whatever the client shows."""
    document.status = StockDocument.objects.select_for_update().get(pk=document.pk).status
    if document.status != StockDocument.Status.DRAFT:
        raise StockDocumentLocked("لا يُعدَّل إلا المستند المسودة — هذا المستند مرحَّل أو قيد الاعتماد.")
    if document.kind == StockDocument.Kind.COUNT:
        raise ValidationError("أسطر جلسة الجرد تُملأ من الأرصدة عند فتحها — أدخل العدّ أو استورده، ولا تُعدَّل الأسطر.")
    if raw_lines is None:
        raw_lines = [
            {
                "item": line.item_id, "uom": line.uom_id, "qty": line.qty, "unit_cost": line.unit_cost,
                "cost_center": line.cost_center_id, "batch": line.batch_id,
                "serials": [s.serial for s in line.serials.all()],
            }
            for line in document.lines.all()
        ]
    resolved_lines = resolve_stock_lines(document.tenant, document.kind, raw_lines)
    data = {**{name: getattr(document, name) for name in _HEADER_FIELDS}, **data, "kind": document.kind}
    _validate_header(document.tenant, data)
    if not resolved_lines:
        raise ValidationError("المستند يحتاج سطرًا واحدًا على الأقل.")
    for name in _HEADER_FIELDS:
        setattr(document, name, data.get(name))
    document.save(update_fields=[name for name in _HEADER_FIELDS if name != "kind"])
    document.lines.all().delete()
    _write_lines(document, resolved_lines)
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER, actor_id=user.id, action="stock_document.updated",
        target_type="stock_document", target_id=document.id, tenant_id=document.tenant_id, request=request,
    )
    return document


def document_totals(document):
    """Server-side totals — never accepted from a client.
    - POSTED/REVERSED: the real value that left/entered the document's own
      warehouse (Σ StockMove.value there), exact.
    - Earlier states: a receipt's Σ qty_base x unit_cost (exact — the
      user entered the cost); an issue/transfer's value at the CURRENT
      company average, flagged `is_estimate` (the real cost is only fixed
      at posting)."""
    from django.db.models import DecimalField, ExpressionWrapper, Sum

    if document.kind == StockDocument.Kind.COUNT:
        return _count_totals(document)
    total_qty = document.lines.aggregate(q=Sum("qty_base"))["q"] or Decimal("0")
    if document.status in (StockDocument.Status.POSTED, StockDocument.Status.REVERSED):
        moved = StockMove.objects.filter(document=document, warehouse_id=document.warehouse_id).aggregate(
            v=Sum("value")
        )["v"] or Decimal("0")
        return {"total_qty": total_qty, "total_value": abs(moved), "is_estimate": False}
    if document.kind == StockDocument.Kind.RECEIPT:
        value = document.lines.aggregate(
            v=Sum(ExpressionWrapper(F("qty_base") * F("unit_cost"), output_field=DecimalField()))
        )["v"] or Decimal("0")
        return {"total_qty": total_qty, "total_value": _money(value), "is_estimate": False}
    company = company_entity_for(document.warehouse.legal_entity)
    per_item = document.lines.values("item_id").annotate(q=Sum("qty_base"))
    averages = dict(
        ItemCost.objects.filter(company_entity=company, item_id__in=[r["item_id"] for r in per_item]).values_list(
            "item_id", "avg_cost"
        )
    )
    value = sum((r["q"] * averages.get(r["item_id"], Decimal("0")) for r in per_item), Decimal("0"))
    return {"total_qty": total_qty, "total_value": _money(value), "is_estimate": True}


def submit_stock_document(document, user, request=None):
    """DRAFT -> PENDING_APPROVAL, auto-approved when no ApprovalRule
    matches (apps.approvals.submit_for_approval). Returns True if it ended
    APPROVED."""
    from apps.approvals.services import submit_for_approval

    if not document.lines.exists():
        raise ValidationError("لا يُرسَل للاعتماد مستند بلا سطور.")
    if document.kind == StockDocument.Kind.COUNT:
        if not document.lines.filter(counted_qty__isnull=False).exists():
            raise ValidationError("لم يُدخَل عدّ لأي سطر في جلسة الجرد — أدخل العدّ قبل الإرسال للاعتماد.")
        # The posting refuses a zero-cost surplus (_plan_count_moves); say
        # so here too, while the session is still a draft and the cost can
        # still be entered.
        lines = {line.id: line for line in document.lines.select_related("item")}
        zero_cost = [
            (lines[int(row["line"])].item, row["variance_qty"])
            for row in count_variances(document)["lines"] if row["needs_cost"]
        ]
        if zero_cost:
            raise ValidationError(zero_cost_surplus_message(zero_cost))
    amount = document_totals(document)["total_value"]
    return submit_for_approval(document, user, approval_doc_type(document), amount, request=request)


@transaction.atomic
def approve_stock_document(document, user, request=None, emergency_reason=""):
    from apps.approvals.services import approve

    amount = document_totals(document)["total_value"]
    approve(document, user, approval_doc_type(document), amount, request=request, emergency_reason=emergency_reason)
    return document


def reject_stock_document(document, user, reason, request=None):
    from apps.approvals.services import reject

    return reject(document, user, approval_doc_type(document), reason, request=request)


def withdraw_stock_document(document, user, request=None):
    from apps.approvals.services import withdraw

    return withdraw(document, user, approval_doc_type(document), request=request)


# ---------------------------------------------------------------------------
# Sprint 7.5 (D16): count sessions — a StockDocument of kind COUNT.
#
# Open: lines filled from the warehouse's balances (expected_qty = the
# snapshot). Count: counted_qty per line, by hand or from a CSV — both go
# through set_counts, all-or-nothing. Variances: count_variances, against
# the balance NOW (not the snapshot). Post: the 7.3 engine
# (_plan_count_moves). Freeze: _assert_not_frozen, inside the engine.
# ---------------------------------------------------------------------------


class CountEntryErrors(Exception):
    """Every problem in one counts submission (manual or CSV), each with
    its row number and reason. Nothing is applied when this is raised."""

    def __init__(self, errors):
        super().__init__("; ".join(f"{e['row']}: {e['reason']}" for e in errors))
        self.errors = errors


# What a counter is told about anything found on the shelf that the
# session can't take: it goes in on a receipt first, then gets counted.
NOT_IN_WAREHOUSE = "غير مسجَّل في هذا المستودع — أدخله بإذن إضافة من «أذون الإضافة» ثم أعد العدّ."


def _category_ids_under(category):
    from .models import ItemCategory

    ids, frontier = {category.id}, [category.id]
    while frontier:
        frontier = list(
            ItemCategory.objects.filter(parent_id__in=frontier, deleted_at__isnull=True).values_list("id", flat=True)
        )
        frontier = [i for i in frontier if i not in ids]
        ids.update(frontier)
    return ids


@transaction.atomic
def create_count_session(tenant, user, data, category=None, search="", request=None):
    """Open a count session on one warehouse: one line per item with a
    balance row there (per batch for a batch-tracked item), expected_qty =
    the balance now. `category` (with its sub-categories) and/or `search`
    (code or name) narrow it to a partial count; items outside the scope
    get no line and so can never move. One open session per warehouse."""
    from django.db.models import Q as _Q

    from apps.sales.models import Product

    data = {**data, "kind": StockDocument.Kind.COUNT, "to_warehouse": None}
    _validate_header(tenant, data)
    warehouse = data["warehouse"]
    existing = open_count_sessions(tenant, [warehouse.id]).first()
    if existing is not None:
        raise ValidationError(
            f"على المستودع «{warehouse.name}» جلسة جرد مفتوحة {count_session_label(existing)} — "
            "رحّلها أو احذفها قبل فتح جلسة جديدة."
        )

    items = Product.objects.filter(tenant=tenant, item_type=Product.ItemType.STOCK, deleted_at__isnull=True)
    scope = []
    if category is not None:
        items = items.filter(category_id__in=_category_ids_under(category))
        scope.append(f"الفئة {category.name}")
    search = (search or "").strip()
    if search:
        items = items.filter(_Q(sku__icontains=search) | _Q(name__icontains=search))
        scope.append(f"بحث «{search}»")

    specs = []
    levels = (
        StockLevel.objects.filter(warehouse=warehouse, item__in=items)
        .select_related("item").order_by("item__sku", "item__name")
    )
    for level in levels:
        item = level.item
        if item.tracking == InventorySettings.Tracking.BATCH:
            for bs in (
                BatchStock.objects.filter(warehouse=warehouse, batch__item=item)
                .select_related("batch").order_by(F("batch__expiry").asc(nulls_last=True), "batch__number")
            ):
                specs.append((item, bs.batch, bs.qty))
        else:
            specs.append((item, None, level.qty_on_hand))
    if not specs:
        raise ValidationError("لا أصناف لها رصيد في هذا المستودع ضمن نطاق الجرد المختار.")

    document = StockDocument.objects.create(
        tenant=tenant, created_by=user, status=StockDocument.Status.DRAFT, kind=StockDocument.Kind.COUNT,
        legal_entity=data["legal_entity"], warehouse=warehouse, date=data["date"],
        account=data.get("account"), reference=data.get("reference", ""), notes=data.get("notes", ""),
        count_scope="، ".join(scope),
    )
    StockDocumentLine.objects.bulk_create(
        [
            StockDocumentLine(
                document=document, item=item, batch=batch, qty=_ZERO, qty_base=_ZERO, expected_qty=expected,
            )
            for item, batch, expected in specs
        ]
    )
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER, actor_id=user.id, action="stock_document.created",
        target_type="stock_document", target_id=document.id, tenant_id=tenant.id,
        after={"kind": "count", "lines": len(specs), "scope": document.count_scope}, request=request,
    )
    return document


def _parse_qty(text):
    from decimal import InvalidOperation

    try:
        value = Decimal(str(text).strip().replace("٫", ".").translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")))
    except InvalidOperation:
        return None
    if not value.is_finite() or value.as_tuple().exponent < -2:
        return None
    return value


@transaction.atomic
def set_counts(document, user, entries, request=None, source="manual", errors=None):
    """Apply counted quantities to a DRAFT count session — all of them or
    none. `entries`: [{"row", "line" (id), "counted_qty" (str, "" / None
    = not counted), "serials" (list of serial strings)}]. Every bad row is
    collected (row number + reason) and raised together as
    CountEntryErrors; nothing is written unless every row is valid."""
    document.status = StockDocument.objects.select_for_update().get(pk=document.pk).status
    if document.kind != StockDocument.Kind.COUNT:
        raise ValidationError("إدخال العدّ لجلسات الجرد فقط.")
    if document.status != StockDocument.Status.DRAFT:
        raise StockDocumentLocked("لا يُعدَّل العدّ إلا في جلسة جرد مسودة.")

    lines = {str(line.id): line for line in document.lines.select_related("item", "batch")}
    # `errors`: problems the caller already found (a CSV row matching no
    # line) — reported together with these, never applied around.
    errors, updates, seen = list(errors or []), [], {}
    for entry in entries:
        row = entry["row"]
        line = lines.get(str(entry.get("line")))
        if line is None:
            errors.append({"row": row, "reason": "السطر ليس من هذه الجلسة."})
            continue
        if str(line.id) in seen:
            errors.append({"row": row, "reason": f"الصنف «{line.item.name}» مكرر (ورد في الصف {seen[str(line.id)]})."})
            continue
        seen[str(line.id)] = row
        raw_qty = entry.get("counted_qty")
        serial_texts = [t.strip() for t in entry.get("serials") or [] if t and t.strip()]
        is_serial = line.item.tracking == InventorySettings.Tracking.SERIAL
        if raw_qty in (None, "") and not serial_texts:
            updates.append((line, None, []))  # not counted
            continue
        qty = None
        if raw_qty not in (None, ""):
            qty = _parse_qty(raw_qty)
            if qty is None:
                errors.append({"row": row, "reason": f"الكمية «{raw_qty}» ليست رقمًا صالحًا (خانتان عشريتان كحد أقصى)."})
                continue
            if qty < 0:
                errors.append({"row": row, "reason": "الكمية المعدودة لا تكون سالبة."})
                continue
        if not is_serial:
            if serial_texts:
                errors.append({"row": row, "reason": f"الصنف «{line.item.name}» غير متتبَّع بالسيريال."})
                continue
            updates.append((line, qty, []))
            continue
        if len(set(serial_texts)) != len(serial_texts):
            errors.append({"row": row, "reason": "سيريال مكرر في الصف نفسه."})
            continue
        if qty is not None and qty != len(serial_texts):
            errors.append({
                "row": row,
                "reason": f"الصنف «{line.item.name}» متتبَّع بالسيريال: الكمية {_fmt_qty(qty)} وعدد السيريالات {len(serial_texts)}.",
            })
            continue
        found = {
            sn.serial: sn
            for sn in SerialNumber.objects.filter(
                tenant=document.tenant, item=line.item, serial__in=serial_texts,
                status=SerialNumber.Status.IN_STOCK, warehouse=document.warehouse,
            )
        }
        unknown = [t for t in serial_texts if t not in found]
        if unknown:
            # Every unknown serial is named — none is dropped. One that is in
            # this warehouse under another item was scanned on the wrong line.
            elsewhere = dict(
                SerialNumber.objects.filter(
                    tenant=document.tenant, serial__in=unknown, status=SerialNumber.Status.IN_STOCK,
                    warehouse=document.warehouse,
                ).exclude(item=line.item).values_list("serial", "item__name")
            )
            reasons = [
                f"السيريال {t} للصنف «{elsewhere[t]}» لا «{line.item.name}» — امسحه في سطر صنفه."
                for t in unknown if t in elsewhere
            ]
            missing = [t for t in unknown if t not in elsewhere]
            if missing:
                reasons.insert(0, f"السيريال {', '.join(missing)} {NOT_IN_WAREHOUSE}")
            errors.append({"row": row, "reason": " ".join(reasons)})
            continue
        updates.append((line, Decimal(len(serial_texts)), [found[t].id for t in serial_texts]))

    if errors:
        raise CountEntryErrors(sorted(errors, key=lambda e: e["row"]))
    for line, qty, _serial_ids in updates:
        line.counted_qty = qty
    StockDocumentLine.objects.bulk_update([u[0] for u in updates], ["counted_qty"])
    for line, _qty, serial_ids in updates:
        if line.item.tracking == InventorySettings.Tracking.SERIAL:
            line.counted_serials.set(serial_ids)
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER, actor_id=user.id, action="stock_document.counts_entered",
        target_type="stock_document", target_id=document.id, tenant_id=document.tenant_id,
        after={"source": source, "rows": len(updates)}, request=request,
    )
    return document


@transaction.atomic
def set_surplus_costs(document, user, entries, request=None):
    """The unit cost a count surplus enters at, per line. `entries`:
    [{"row", "line", "unit_cost" (str; "" / None = back to the average)}].
    All or nothing, like set_counts. Every change goes to the audit log
    (before / after per line) — the document's change history.

    DRAFT, or APPROVED and not yet posted. The approver approved an amount,
    and the cost changes it: on an APPROVED session a real change sends it
    back to DRAFT — the approval is void, the counts stay — and it posts
    only after a new approval (post_stock_document wants APPROVED). This is
    count-only: apps.approvals has no general approved -> draft path
    (reject/withdraw start from PENDING_APPROVAL), and a session's counts
    are physical work that a line turning into a zero-cost surplus after
    approval must not throw away."""
    document.status = StockDocument.objects.select_for_update().get(pk=document.pk).status
    if document.kind != StockDocument.Kind.COUNT:
        raise ValidationError("تكلفة وحدة الزيادة لجلسات الجرد فقط.")
    if document.status == StockDocument.Status.PENDING_APPROVAL:
        raise StockDocumentLocked(
            "الجلسة بانتظار الاعتماد — لا تُعدَّل تكلفة الزيادة حتى تُسحب أو تُرفض فتعود مسودة."
        )
    if document.status not in (StockDocument.Status.DRAFT, StockDocument.Status.APPROVED):
        raise StockDocumentLocked("لا تُعدَّل تكلفة الزيادة إلا في جلسة جرد مسودة أو معتمدة لم تُرحَّل.")

    lines = {str(line.id): line for line in document.lines.select_related("item")}
    errors, updates, seen = [], [], {}
    for entry in entries:
        row = entry["row"]
        line = lines.get(str(entry.get("line")))
        if line is None:
            errors.append({"row": row, "reason": "السطر ليس من هذه الجلسة."})
            continue
        if str(line.id) in seen:
            errors.append({"row": row, "reason": f"الصنف «{line.item.name}» مكرر (ورد في الصف {seen[str(line.id)]})."})
            continue
        seen[str(line.id)] = row
        if line.item.tracking == InventorySettings.Tracking.SERIAL:
            errors.append({
                "row": row,
                "reason": f"الصنف «{line.item.name}» متتبَّع بالسيريال — لا زيادة له في الجرد، فلا تكلفة زيادة.",
            })
            continue
        raw = entry.get("unit_cost")
        cost = None
        if raw not in (None, ""):
            cost = _parse_qty(raw)
            if cost is None:
                errors.append({"row": row, "reason": f"التكلفة «{raw}» ليست رقمًا صالحًا (خانتان عشريتان كحد أقصى)."})
                continue
            if cost <= 0:
                errors.append({
                    "row": row,
                    "reason": f"تكلفة وحدة الزيادة للصنف «{line.item.name}» يجب أن تكون أكبر من صفر.",
                })
                continue
            cost = _money(cost)
        if line.surplus_unit_cost != cost:
            updates.append((line, cost))

    if errors:
        raise CountEntryErrors(sorted(errors, key=lambda e: e["row"]))
    if not updates:
        return document

    def text(cost):
        return None if cost is None else str(cost)

    before = [{"line": line.id, "item": line.item.name, "sku": line.item.sku, "unit_cost": text(line.surplus_unit_cost)}
              for line, _cost in updates]
    after = [{"line": line.id, "item": line.item.name, "sku": line.item.sku, "unit_cost": text(cost)}
             for line, cost in updates]
    for line, cost in updates:
        line.surplus_unit_cost = cost
    StockDocumentLine.objects.bulk_update([u[0] for u in updates], ["surplus_unit_cost"])
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER, actor_id=user.id, action="stock_document.surplus_cost_set",
        target_type="stock_document", target_id=document.id, tenant_id=document.tenant_id,
        before={"lines": before}, after={"lines": after}, request=request,
    )
    if document.status == StockDocument.Status.APPROVED:
        _void_count_approval(document, user, after, request=request)
    return document


def _void_count_approval(document, user, changed_lines, request=None):
    """APPROVED -> DRAFT because the amount changed. Logged twice, on
    purpose: on the document (its change history, which reads
    target_type="stock_document") and in the approvals trail
    (target_type="stock_count", next to its .submitted/.approved), so
    neither record shows an approval that silently stopped counting."""
    from apps.approvals.services import _log as log_approval_event

    reason = "تغيّرت تكلفة وحدة الزيادة بعد الاعتماد — المبلغ المعتمد لم يعد مبلغ الجلسة."
    document.status = StockDocument.Status.DRAFT
    document.save(update_fields=["status"])
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER, actor_id=user.id, action="stock_document.approval_voided",
        target_type="stock_document", target_id=document.id, tenant_id=document.tenant_id,
        before={"status": StockDocument.Status.APPROVED}, after={"status": StockDocument.Status.DRAFT, "reason": reason},
        request=request,
    )
    log_approval_event(
        document, approval_doc_type(document), user, "approval_voided",
        after={"reason": reason, "lines": changed_lines}, request=request,
    )


def find_count_item(document, query):
    """«صنف وُجد وليس في الورقة» on the count screen: a counter found something the sheet
    doesn't list. A session never takes manual lines — this only says
    where the thing goes: its existing line ({"line", "message"}), or a
    ValidationError naming exactly why it can't be counted here. `query`
    is a serial, a code, a barcode, or (one match only) part of a name."""
    from apps.sales.models import Product

    query = (query or "").strip()
    if not query:
        raise ValidationError("اكتب رمز الصنف أو الباركود أو السيريال.")
    warehouse = document.warehouse
    lines = {}
    for line in document.lines.select_related("item").order_by("id"):
        lines.setdefault(line.item_id, line)

    serial = (
        SerialNumber.objects.filter(tenant=document.tenant, serial=query)
        .select_related("item", "warehouse").first()
    )
    if serial is not None:
        here = serial.status == SerialNumber.Status.IN_STOCK and serial.warehouse_id == warehouse.id
        if not here:
            raise ValidationError(f"السيريال {serial.serial} للصنف «{serial.item.name}» {NOT_IN_WAREHOUSE}")
        if serial.item_id not in lines:
            raise ValidationError(
                f"السيريال {serial.serial} للصنف «{serial.item.name}» خارج نطاق هذه الجلسة "
                f"({document.count_scope}) — يُعدّ في جلسة جرد لاحقة على هذا المستودع."
            )
        line = lines[serial.item_id]
        return {"line": line.id, "message": f"السيريال {serial.serial} للصنف «{line.item.name}» — امسحه في سطر الصنف."}

    products = Product.objects.filter(tenant=document.tenant, deleted_at__isnull=True)
    item = (
        products.filter(sku__iexact=query).first()
        or products.filter(
            barcodes__barcode=query, barcodes__is_active=True, barcodes__deleted_at__isnull=True
        ).first()
    )
    if item is None:
        matches = list(products.filter(Q(sku__icontains=query) | Q(name__icontains=query))[:6])
        if not matches:
            raise ValidationError(
                f"لا صنف ولا سيريال بالرمز «{query}». إن كان سيريالًا فهو {NOT_IN_WAREHOUSE}"
            )
        if len(matches) > 1:
            names = "، ".join(f"«{p.name}» ({p.sku})" for p in matches[:5])
            raise ValidationError(f"أكثر من صنف يطابق «{query}»: {names} — اكتب الرمز كاملًا.")
        item = matches[0]
    if item.item_type != Product.ItemType.STOCK:
        raise ValidationError(f"«{item.name}» ليس صنفًا مخزنيًا — لا يُجرد.")
    if item.id in lines:
        return {"line": lines[item.id].id, "message": f"الصنف «{item.name}» في الجلسة — أدخل عدّه في سطره."}
    if StockLevel.objects.filter(item=item, warehouse=warehouse).exists():
        raise ValidationError(
            f"الصنف «{item.name}» خارج نطاق هذه الجلسة ({document.count_scope}) — "
            "يُعدّ في جلسة جرد لاحقة على هذا المستودع."
        )
    raise ValidationError(f"الصنف «{item.name}» ({item.sku}): هذا الصنف {NOT_IN_WAREHOUSE}")


COUNT_CSV_COLUMNS = ("sku", "batch", "counted_qty", "serials")


def import_counts_csv(document, user, text, request=None):
    """CSV with a header row: sku, batch (blank for a non-batch item),
    counted_qty, serials (space- or ;-separated, serial items only). Row
    numbers in errors are the file's own line numbers (header = 1). Atomic:
    one bad row and nothing is applied (set_counts)."""
    import csv
    import io

    reader = csv.reader(io.StringIO(text.lstrip("\ufeff")))
    rows = list(reader)
    if not rows:
        raise CountEntryErrors([{"row": 1, "reason": "الملف فارغ."}])
    header = [h.strip().lower() for h in rows[0]]
    missing = [c for c in ("sku", "counted_qty") if c not in header]
    if missing:
        raise CountEntryErrors([{
            "row": 1, "reason": f"العمودان المطلوبان: sku وcounted_qty (الناقص: {', '.join(missing)}). "
            f"الأعمدة المقبولة: {', '.join(COUNT_CSV_COLUMNS)}.",
        }])
    col = {name: header.index(name) for name in COUNT_CSV_COLUMNS if name in header}

    by_key = {}
    for line in document.lines.select_related("item", "batch"):
        by_key[(line.item.sku.strip().lower(), (line.batch.number if line.batch else "").strip().lower())] = line

    def cell(values, name):
        index = col.get(name)
        return values[index].strip() if index is not None and index < len(values) else ""

    entries, errors = [], []
    for number, values in enumerate(rows[1:], start=2):
        if not any(v.strip() for v in values):
            continue
        sku, batch = cell(values, "sku"), cell(values, "batch")
        line = by_key.get((sku.lower(), batch.lower()))
        if line is None:
            what = f"الصنف «{sku}»" + (f" بالدفعة «{batch}»" if batch else "")
            errors.append({"row": number, "reason": f"{what} ليس ضمن أسطر هذه الجلسة."})
            continue
        qty = cell(values, "counted_qty")
        serials = [t for t in cell(values, "serials").replace(";", " ").split() if t]
        if qty == "" and not serials:
            errors.append({"row": number, "reason": "الكمية المعدودة فارغة — احذف الصف إن لم يُعدّ الصنف."})
            continue
        entries.append({"row": number, "line": str(line.id), "counted_qty": qty, "serials": serials})
    return set_counts(document, user, entries, request=request, source="csv", errors=errors)


def count_drift(document):
    """Counted lines whose balance moved since the session opened:
    [{line, item, batch, expected, current, change}]. Empty = the snapshot
    still holds."""
    return [
        {k: row[k] for k in ("line", "item_name", "batch_number", "expected_qty", "current_qty", "drift")}
        for row in count_variances(document)["lines"]
        if row["counted_qty"] is not None and row["drift"]
    ]


def count_variances(document):
    """The variance tab. Before posting: per line, the snapshot
    (expected_qty), the balance NOW, the counted quantity, the variance it
    will post (counted − now — not counted − snapshot), its value at the
    current company average (a surplus at its entered surplus_unit_cost
    when there is one), and the drift (now − snapshot). After posting:
    the variance and value the posting actually moved (StockMove)."""
    from django.db.models import Sum

    company = company_entity_for(document.warehouse.legal_entity)
    lines = list(document.lines.select_related("item", "batch").order_by("id"))
    averages = dict(
        ItemCost.objects.filter(company_entity=company, item_id__in={line.item_id for line in lines}).values_list(
            "item_id", "avg_cost"
        )
    )
    posted = document.status in (StockDocument.Status.POSTED, StockDocument.Status.REVERSED)
    moved = {}
    if posted:
        moved = {
            r["line_id"]: r["v"]
            for r in StockMove.objects.filter(document=document, warehouse_id=document.warehouse_id)
            .values("line_id").annotate(v=Sum("value"))
        }
    levels = dict(
        StockLevel.objects.filter(warehouse=document.warehouse, item_id__in={line.item_id for line in lines})
        .values_list("item_id", "qty_on_hand")
    )
    batch_levels = dict(
        BatchStock.objects.filter(
            warehouse=document.warehouse, batch_id__in={line.batch_id for line in lines if line.batch_id}
        ).values_list("batch_id", "qty")
    )

    rows, shortage, surplus = [], _ZERO, _ZERO
    for line in lines:
        avg = averages.get(line.item_id, _ZERO)
        current = batch_levels.get(line.batch_id, _ZERO) if line.batch_id else levels.get(line.item_id, _ZERO)
        if posted:
            variance = line.qty_base if line.counted_qty is not None else None
            value = moved.get(line.id, _ZERO) if variance is not None else None
        elif line.counted_qty is not None:
            variance = line.counted_qty - current
            unit = line.surplus_unit_cost if variance > 0 and line.surplus_unit_cost is not None else avg
            value = _money(variance * unit)
        else:
            variance = value = None
        if value is not None and value < 0:
            shortage -= value
        elif value is not None:
            surplus += value
        rows.append({
            "line": str(line.id),
            "item": str(line.item_id),
            "item_name": line.item.name,
            "item_sku": line.item.sku,
            "batch_number": line.batch.number if line.batch else None,
            "expected_qty": line.expected_qty,
            "current_qty": None if posted else current,
            "counted_qty": line.counted_qty,
            "variance_qty": variance,
            "avg_cost": avg,
            "surplus_unit_cost": line.surplus_unit_cost,
            # A surplus the posting would refuse: zero average, no cost entered.
            "needs_cost": bool(not posted and variance is not None and variance > 0
                               and line.surplus_unit_cost is None and not avg),
            "variance_value": value,
            "drift": None if posted else (current - (line.expected_qty or _ZERO)),
        })
    return {
        "lines": rows,
        "shortage_value": _money(shortage),
        "surplus_value": _money(surplus),
        "net_value": _money(surplus - shortage),
        "counted_lines": sum(1 for line in lines if line.counted_qty is not None),
        "total_lines": len(lines),
    }


def _count_totals(document):
    """A count's totals: the gross variance value (shortage + surplus) —
    the amount the approval rule is judged on and the list shows —
    estimated at the current average until posted."""
    report = count_variances(document)
    qty = sum((r["variance_qty"] for r in report["lines"] if r["variance_qty"] is not None), _ZERO)
    posted = document.status in (StockDocument.Status.POSTED, StockDocument.Status.REVERSED)
    return {
        "total_qty": qty,
        "total_value": report["shortage_value"] + report["surplus_value"],
        "is_estimate": not posted,
    }
