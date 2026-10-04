from .models import InventorySettings

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
