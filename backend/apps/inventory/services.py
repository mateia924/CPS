from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from .models import InventorySettings, ItemUoM

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
