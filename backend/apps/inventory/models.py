from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.constants import QUANTITY_DECIMAL_PLACES, QUANTITY_MAX_DIGITS
from apps.common.models import SoftDeleteModelMixin, TenantScopedModel


class InventorySettings(models.Model):
    """Sprint 7.0 — one row per tenant, same aux-table shape as
    apps.tenants.models.TenantFeatures (plain Model, OneToOneField,
    never a TenantScopedModel UUID row — there is exactly one of these
    per tenant, never a list a client could create/delete). Every
    field named across sprint-7.md's decisions (D3, D11, D16, D18) is
    collected here up front rather than one migration per decision,
    since the whole set was already known before this model was first
    written — still additive-only from here on, same as every other
    model in this project.

    Created lazily (get_or_create) on first read/write via
    InventorySettingsView, not at tenant registration — same pattern
    apps.numbering.services.get_or_create_numbering_setting already
    uses for DocumentNumberingSetting.
    """

    class Tracking(models.TextChoices):
        NONE = "none", _("None")
        SERIAL = "serial", _("Serial")
        BATCH = "batch", _("Batch")

    tenant = models.OneToOneField(
        "tenants.Tenant", on_delete=models.CASCADE, related_name="inventory_settings"
    )
    # D3 (R-7.2): the owner's own recommendation (S6) is the default —
    # posting a stock document past the available quantity is rejected
    # with 400 unless a tenant explicitly opts into a warning instead.
    allow_negative_stock = models.BooleanField(_("allow negative stock"), default=False)
    # D11: days before a batch's expiry that it starts surfacing in
    # the expiry report / daily email digest.
    expiry_alert_days = models.PositiveIntegerField(_("expiry alert days"), default=30)
    # D16: blocks posting any OTHER stock document against a warehouse
    # while a count session on it is open.
    freeze_warehouse_during_count = models.BooleanField(_("freeze warehouse during count"), default=True)
    # D18: apply_item_feature_defaults' own default for a NEW item
    # category going forward — never retroactively changes an existing
    # category's own already-chosen tracking.
    default_tracking = models.CharField(
        _("default tracking"), max_length=10, choices=Tracking.choices, default=Tracking.NONE
    )
    show_weight_karat_fields = models.BooleanField(_("show weight/karat fields"), default=False)
    units_enabled = models.BooleanField(_("units of measure enabled"), default=False)
    barcode_enabled = models.BooleanField(_("barcode enabled"), default=False)

    class Meta:
        verbose_name = _("inventory settings")
        verbose_name_plural = _("inventory settings")

    def __str__(self):
        return f"inventory settings for {self.tenant_id}"


class ItemCategory(TenantScopedModel, SoftDeleteModelMixin):
    """Sprint 7.1 (D7/D18): a tree of item categories, same self-FK/
    cycle-check shape as apps.organization.models.CostCenter — no
    `level`/`can_post`-style computed fields here (nothing posts
    directly to a category the way it posts to an Account), just the
    tree itself plus the DEFAULT properties a new item in this
    category should start with (D18's "التتبع، الوحدة، الحسابات").
    These are defaults only, copied onto a new Item at creation time
    (apps.sales.services, sprint 7.1) — changing a category's defaults
    later never retroactively changes an existing item's own already-
    set values, same non-retroactive rule InventorySettings.
    default_tracking's own docstring already states for new categories
    themselves."""

    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )
    code = models.CharField(_("code"), max_length=20)
    name = models.CharField(_("name"), max_length=255)
    default_tracking = models.CharField(
        _("default tracking"), max_length=10, choices=InventorySettings.Tracking.choices,
        blank=True, default="",
    )
    default_uom = models.ForeignKey(
        "inventory.UnitOfMeasure", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    default_inventory_account = models.ForeignKey(
        "accounting.Account", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    default_cogs_account = models.ForeignKey(
        "accounting.Account", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = _("item categories")
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "code"], name="unique_item_category_code_per_tenant"
            )
        ]

    def __str__(self):
        return f"{self.code} {self.name}"

    def clean(self):
        if not self.parent_id:
            return
        if self.parent_id == self.id:
            raise ValidationError(_("A category cannot be its own parent."))
        node = self.parent
        seen = set()
        while node is not None:
            if node.id == self.id or node.id in seen:
                raise ValidationError(_("This would create a cycle in the item category tree."))
            seen.add(node.id)
            node = node.parent


class UnitOfMeasure(TenantScopedModel, SoftDeleteModelMixin):
    """Sprint 7.1 (D8): `code` + `name_ar` only — the conversion
    factor to an item's own base unit lives on ItemUoM below, never
    here, since "كرتونة = 12 قطعة" is a fact about a SPECIFIC item
    (a different item's own "كرتونة" could hold a different count),
    not about the carton unit itself."""

    code = models.CharField(_("code"), max_length=20)
    name_ar = models.CharField(_("Arabic name"), max_length=100)
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("unit of measure")
        verbose_name_plural = _("units of measure")
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="unique_uom_code_per_tenant")
        ]

    def __str__(self):
        return self.name_ar


class ItemUoM(TenantScopedModel, SoftDeleteModelMixin):
    """Sprint 7.1 (D8): one row per (item, alternate unit) — the
    factor that converts a document line's `qty` in this unit to
    `qty_base` in the item's own `base_uom` (sprint 7.1 appendix: "كل
    سطر مستند يحمل uom + qty + qty_base المحسوبة خادميًا"). The item's
    base_uom itself never needs its own ItemUoM row (factor is
    definitionally 1) — this table only holds the ALTERNATE units."""

    item = models.ForeignKey("sales.Product", on_delete=models.CASCADE, related_name="uoms")
    uom = models.ForeignKey("inventory.UnitOfMeasure", on_delete=models.PROTECT, related_name="+")
    factor_to_base = models.DecimalField(
        _("factor to base unit"), max_digits=QUANTITY_MAX_DIGITS, decimal_places=QUANTITY_DECIMAL_PLACES,
    )
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("item unit of measure")
        verbose_name_plural = _("item units of measure")
        constraints = [
            models.UniqueConstraint(fields=["item", "uom"], name="unique_item_uom_per_item")
        ]

    def __str__(self):
        return f"{self.item_id}: {self.uom} = {self.factor_to_base}×base"


class ItemBarcode(TenantScopedModel, SoftDeleteModelMixin):
    """Sprint 7.1 (D9): a barcode is unique per TENANT, not per item —
    two different items can never share one, so the uniqueness
    constraint deliberately omits `item`. `uom`: scanning a carton's
    own barcode should fill the line's unit as "carton" automatically
    (sprint 7.1 appendix) — null means the item's own base_uom."""

    item = models.ForeignKey("sales.Product", on_delete=models.CASCADE, related_name="barcodes")
    barcode = models.CharField(_("barcode"), max_length=64)
    uom = models.ForeignKey(
        "inventory.UnitOfMeasure", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("item barcode")
        verbose_name_plural = _("item barcodes")
        constraints = [
            models.UniqueConstraint(fields=["tenant", "barcode"], name="unique_barcode_per_tenant")
        ]

    def __str__(self):
        return self.barcode
