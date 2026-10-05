from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import F
from django.utils.translation import gettext_lazy as _

from .models import BatchStock, InventorySettings, ItemUoM

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
