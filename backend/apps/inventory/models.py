from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils.translation import gettext_lazy as _

from apps.common.constants import (
    MONEY_DECIMAL_PLACES,
    MONEY_MAX_DIGITS,
    PRICE_DECIMAL_PLACES,
    PRICE_MAX_DIGITS,
    QUANTITY_DECIMAL_PLACES,
    QUANTITY_MAX_DIGITS,
)
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


class Warehouse(TenantScopedModel, SoftDeleteModelMixin):
    """Sprint 7.2 (block spec, item 1): one legal_entity is mandatory —
    a warehouse belongs to exactly one branch (or the company itself
    in simplified mode), never shared across entities (ItemCost below
    is the company-wide sharing mechanism; Warehouse/StockLevel are
    deliberately NOT). The three optional account overrides mirror
    Product's own inventory_account_override/cogs_account_override
    pattern (sprint 7.1) — INVENTORY_ADJUSTMENT is the third because
    rounding corrections (D2) need somewhere to post per-warehouse too
    when a tenant wants that split; GRNI/GOODS_IN_TRANSIT are
    purchasing-flow-wide, never a per-warehouse override."""

    legal_entity = models.ForeignKey(
        "organization.LegalEntity", on_delete=models.PROTECT, related_name="warehouses"
    )
    code = models.CharField(_("code"), max_length=20)
    name = models.CharField(_("name"), max_length=255)
    inventory_account_override = models.ForeignKey(
        "accounting.Account", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    cogs_account_override = models.ForeignKey(
        "accounting.Account", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    adjustment_account_override = models.ForeignKey(
        "accounting.Account", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    cost_center = models.ForeignKey(
        "organization.CostCenter", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # Sprint 7.2: exactly one default warehouse per legal_entity — the
    # conditional UniqueConstraint below is the hard guarantee (DB
    # level, survives any future caller that forgets the atomic
    # switch); WarehouseSerializer.validate()/save() is what actually
    # performs the atomic switch (unset the old default, set the new
    # one, one transaction) rather than ever naively letting a second
    # True collide with the constraint and surface a raw 500.
    is_default = models.BooleanField(_("default warehouse"), default=False)
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="unique_warehouse_code_per_tenant"),
            models.UniqueConstraint(
                fields=["legal_entity"], condition=models.Q(is_default=True, deleted_at__isnull=True),
                name="unique_default_warehouse_per_entity",
            ),
        ]

    def __str__(self):
        return f"{self.code} {self.name}"


def set_default_warehouse(warehouse):
    """Sprint 7.2: the atomic switch Warehouse.is_default's own
    comment promises — unsets whatever was the old default for this
    warehouse's legal_entity (if any, and if it isn't this same row),
    then sets this one, in one transaction. The DB's own conditional
    UniqueConstraint (unique_default_warehouse_per_entity) is what
    makes a bug here fail loudly instead of silently double-defaulting
    — this function is the one, deliberate way to change which
    warehouse is default; nothing else should flip is_default=True
    directly."""
    with transaction.atomic():
        Warehouse.objects.filter(
            tenant=warehouse.tenant, legal_entity=warehouse.legal_entity, is_default=True,
        ).exclude(pk=warehouse.pk).update(is_default=False)
        warehouse.is_default = True
        warehouse.save(update_fields=["is_default"])


class StockLevel(TenantScopedModel):
    """Sprint 7.2 (D2): quantities PER WAREHOUSE — `qty_reserved` is
    schema only for now (sales-order reservation is a later sprint;
    available_qty already subtracts it so nothing needs to change
    when that lands). No SoftDeleteModelMixin: this is a running
    balance row, maintained by the stock-posting service (sprint 7.3),
    never created/edited/deleted directly by a user."""

    item = models.ForeignKey("sales.Product", on_delete=models.PROTECT, related_name="stock_levels")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="stock_levels")
    qty_on_hand = models.DecimalField(
        _("quantity on hand"), max_digits=QUANTITY_MAX_DIGITS, decimal_places=QUANTITY_DECIMAL_PLACES, default=0,
    )
    qty_reserved = models.DecimalField(
        _("quantity reserved"), max_digits=QUANTITY_MAX_DIGITS, decimal_places=QUANTITY_DECIMAL_PLACES, default=0,
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["item", "warehouse"], name="unique_stock_level_per_item_warehouse")
        ]

    def __str__(self):
        return f"{self.item_id}@{self.warehouse_id}: {self.qty_on_hand}"


def available_qty(item, warehouse):
    """Sprint 7.2 (block spec, item 2): on-hand minus reserved — the
    one function every future screen/report reads stock availability
    through, so the reservation rule (once sales-order reservation
    exists) only ever needs to change here."""
    level = StockLevel.objects.filter(item=item, warehouse=warehouse).first()
    if level is None:
        return Decimal("0")
    return level.qty_on_hand - level.qty_reserved


class ItemCost(TenantScopedModel):
    """Sprint 7.2 (D2/R-7.1): weighted-average cost scoped to the
    COMPANY entity (the nearest ancestor in the legal-entity tree that
    is NOT a branch — never the branch itself), shared by every branch
    under it: "فروع الشركة تشترك بالتكلفة". Quantities for AVAILABILITY
    live per-warehouse in StockLevel above; this row's own qty_on_hand
    is the company-wide total the average is computed over. No
    SoftDeleteModelMixin, same reasoning as StockLevel — a running
    balance, never user-managed directly."""

    item = models.ForeignKey("sales.Product", on_delete=models.PROTECT, related_name="costs")
    company_entity = models.ForeignKey(
        "organization.LegalEntity", on_delete=models.PROTECT, related_name="item_costs"
    )
    qty_on_hand = models.DecimalField(
        _("quantity on hand"), max_digits=QUANTITY_MAX_DIGITS, decimal_places=QUANTITY_DECIMAL_PLACES, default=0,
    )
    total_value = models.DecimalField(
        _("total value"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, default=0,
    )
    avg_cost = models.DecimalField(
        _("average cost"), max_digits=PRICE_MAX_DIGITS, decimal_places=PRICE_DECIMAL_PLACES, default=0,
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["item", "company_entity"], name="unique_item_cost_per_item_company")
        ]

    def __str__(self):
        return f"{self.item_id}@{self.company_entity_id}: avg={self.avg_cost}"


class Batch(TenantScopedModel):
    """Sprint 7.2.5 (D11). Pure tracking — no cost field, deliberately:
    D2 (R-7.1) already answered "where does cost live" with ItemCost's
    own moving weighted average, scoped per company. A cost field here
    would be a second source of truth for the same number, which is
    worse than any single wrong number — if specific-identification
    costing (cost tied to one physical batch) is ever wanted, that is
    a different costing method entirely and needs its own explicit
    decision and sprint, not a field that quietly grew on a tracking
    model.

    `expiry`/`manufactured` are both optional — a batch-tracked item
    with no real expiry concern (lot tracking only) still needs a
    Batch row to group its SerialNumber/BatchStock rows, with no date
    to show."""

    item = models.ForeignKey("sales.Product", on_delete=models.PROTECT, related_name="batches")
    number = models.CharField(_("batch number"), max_length=50)
    expiry = models.DateField(_("expiry"), null=True, blank=True)
    manufactured = models.DateField(_("manufactured"), null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "item", "number"], name="unique_batch_number_per_item")
        ]

    def __str__(self):
        return f"{self.item_id}: {self.number}"

    @property
    def is_expired(self):
        from django.utils import timezone

        return self.expiry is not None and self.expiry < timezone.localdate()


class BatchStock(TenantScopedModel):
    """Sprint 7.2.5 (D11): quantity only, same reasoning as Batch's own
    docstring — cost lives exclusively in ItemCost. A running balance,
    maintained by the posting engine (sprint 7.3) once it exists —
    like StockLevel, never created/edited by a user directly."""

    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="stock")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="batch_stock")
    qty = models.DecimalField(
        _("quantity"), max_digits=QUANTITY_MAX_DIGITS, decimal_places=QUANTITY_DECIMAL_PLACES, default=0,
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["batch", "warehouse"], name="unique_batch_stock_per_batch_warehouse")
        ]

    def __str__(self):
        return f"{self.batch_id}@{self.warehouse_id}: {self.qty}"


class SerialNumber(TenantScopedModel):
    """Sprint 7.2.5 (D11) — covers IMEI/VIN. Pure tracking, no cost
    field (same reasoning as Batch). Uniqueness is scoped to
    (tenant, item, serial) per the decision's own "فريد (مستأجر،
    صنف)" — the same physical serial string is never recorded twice
    for the SAME item in the same tenant; a different item reusing a
    string by coincidence is not blocked (different physical things).

    `received_doc`/`issued_doc`: plain UUIDs, not real ForeignKeys —
    StockDocument (D5) doesn't exist until sprint 7.2.6, built
    deliberately AFTER this block (D11 is independent of the document
    model for its OWN fields — item/warehouse/batch/status — but the
    decision's field list still names these two, so they're captured
    now as loose references that need no later migration to add; only
    sprint 7.3's engine starts POPULATING them with real StockDocument
    ids once that model and the posting service both exist). Same
    "kept loose, upgraded by convention not by schema change" shape
    JournalEntry.source_type/source_id already used in this project
    before it got a real GenericFK."""

    class Status(models.TextChoices):
        IN_STOCK = "in_stock", _("In stock")
        ISSUED = "issued", _("Issued")
        IN_TRANSIT = "in_transit", _("In transit")
        DISPOSED = "disposed", _("Disposed")

    item = models.ForeignKey("sales.Product", on_delete=models.PROTECT, related_name="serial_numbers")
    serial = models.CharField(_("serial number"), max_length=100)
    status = models.CharField(_("status"), max_length=10, choices=Status.choices, default=Status.IN_STOCK)
    warehouse = models.ForeignKey(
        Warehouse, null=True, blank=True, on_delete=models.PROTECT, related_name="serial_numbers"
    )
    batch = models.ForeignKey(Batch, null=True, blank=True, on_delete=models.PROTECT, related_name="serial_numbers")
    received_doc = models.UUIDField(_("received by document"), null=True, blank=True)
    issued_doc = models.UUIDField(_("issued by document"), null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = _("serial numbers")
        constraints = [
            models.UniqueConstraint(fields=["tenant", "item", "serial"], name="unique_serial_per_tenant_item")
        ]

    def __str__(self):
        return self.serial
