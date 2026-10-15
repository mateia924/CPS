from decimal import Decimal

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.accounting.models import Account
from apps.organization.models import CostCenter, LegalEntity
from apps.sales.models import Product

from .models import (
    InventorySettings,
    ItemBarcode,
    ItemCategory,
    ItemUoM,
    StockDocument,
    StockDocumentLine,
    StockLevel,
    UnitOfMeasure,
    Warehouse,
)


class InventorySettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = InventorySettings
        fields = (
            "allow_negative_stock",
            "expiry_alert_days",
            "freeze_warehouse_during_count",
            "default_tracking",
            "show_weight_karat_fields",
            "units_enabled",
            "barcode_enabled",
        )


class ItemCategorySerializer(serializers.ModelSerializer):
    """Sprint 7.1 (D7/D18)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            tenant = request.user.tenant
            self.fields["parent"].queryset = ItemCategory.objects.filter(tenant=tenant, is_active=True)
            self.fields["default_uom"].queryset = UnitOfMeasure.objects.filter(tenant=tenant)
            self.fields["default_inventory_account"].queryset = Account.objects.filter(
                tenant=tenant, is_active=True
            )
            self.fields["default_cogs_account"].queryset = Account.objects.filter(
                tenant=tenant, is_active=True
            )

    class Meta:
        model = ItemCategory
        fields = (
            "id", "parent", "code", "name", "default_tracking", "default_uom",
            "default_inventory_account", "default_cogs_account", "is_active", "created_at",
        )
        read_only_fields = ("id", "created_at")

    def validate(self, attrs):
        parent = attrs.get("parent", getattr(self.instance, "parent", None))
        if parent is None:
            return attrs
        if self.instance is not None and parent.pk == self.instance.pk:
            raise serializers.ValidationError({"parent": [_("A category cannot be its own parent.")]})
        node, seen = parent, set()
        while node is not None:
            if self.instance is not None and (node.pk == self.instance.pk or node.pk in seen):
                raise serializers.ValidationError(
                    {"parent": [_("This would create a cycle in the item category tree.")]}
                )
            seen.add(node.pk)
            node = node.parent
        return attrs


class UnitOfMeasureSerializer(serializers.ModelSerializer):
    class Meta:
        model = UnitOfMeasure
        fields = ("id", "code", "name_ar", "is_active", "created_at")
        read_only_fields = ("id", "created_at")


class ItemUoMSerializer(serializers.ModelSerializer):
    """Sprint 7.1 (D8)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            tenant = request.user.tenant
            self.fields["item"].queryset = Product.objects.filter(tenant=tenant)
            self.fields["uom"].queryset = UnitOfMeasure.objects.filter(tenant=tenant)

    class Meta:
        model = ItemUoM
        fields = ("id", "item", "uom", "factor_to_base", "is_active", "created_at")
        read_only_fields = ("id", "created_at")


class ItemBarcodeSerializer(serializers.ModelSerializer):
    """Sprint 7.1 (D9)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            tenant = request.user.tenant
            self.fields["item"].queryset = Product.objects.filter(tenant=tenant)
            self.fields["uom"].queryset = UnitOfMeasure.objects.filter(tenant=tenant)

    class Meta:
        model = ItemBarcode
        fields = ("id", "item", "barcode", "uom", "is_active", "created_at")
        read_only_fields = ("id", "created_at")

    def validate_barcode(self, value):
        # 7.1 test item 2: a duplicate barcode must fail with a 400
        # naming THIS field — DRF's own UniqueValidator (triggered
        # automatically by the model's UniqueConstraint introspection)
        # already does exactly this for a single-field uniqueness, but
        # the constraint here is (tenant, barcode), not (barcode)
        # alone, so DRF's auto-detection can't see it (no `request` at
        # class-definition time to scope it) — checked explicitly here
        # instead.
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return value
        qs = ItemBarcode.objects.filter(tenant=request.user.tenant, barcode=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(_("This barcode is already used by another item."))
        return value


class WarehouseSerializer(serializers.ModelSerializer):
    """Sprint 7.2 (block spec, item 1)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            tenant = request.user.tenant
            self.fields["legal_entity"].queryset = LegalEntity.objects.filter(tenant=tenant)
            self.fields["cost_center"].queryset = CostCenter.objects.filter(tenant=tenant, is_active=True)
            for field_name in ("inventory_account_override", "cogs_account_override", "adjustment_account_override"):
                self.fields[field_name].queryset = Account.objects.filter(tenant=tenant, is_active=True)

    class Meta:
        model = Warehouse
        fields = (
            "id", "legal_entity", "code", "name", "inventory_account_override", "cogs_account_override",
            "adjustment_account_override", "cost_center", "is_default", "is_active", "created_at",
        )
        read_only_fields = ("id", "created_at")

    def validate(self, attrs):
        # 7.2 test item 2: two defaults in the same entity -> 400 (the
        # DB's own conditional UniqueConstraint is the hard guarantee;
        # this is just the clean 400 instead of a raw IntegrityError
        # for the one case a plain create/update CAN still hit it —
        # explicitly setting is_default=True on a SECOND row without
        # going through set_default_warehouse below).
        is_default = attrs.get("is_default", getattr(self.instance, "is_default", False))
        legal_entity = attrs.get("legal_entity", getattr(self.instance, "legal_entity", None))
        if is_default and legal_entity is not None:
            existing = Warehouse.objects.filter(
                tenant=legal_entity.tenant, legal_entity=legal_entity, is_default=True, deleted_at__isnull=True,
            )
            if self.instance is not None:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                raise serializers.ValidationError(
                    {"is_default": [_(
                        "This entity already has a default warehouse. Use the set-default action "
                        "to switch it instead of setting this field directly."
                    )]}
                )
        return attrs


# ---------------------------------------------------------------------
# Sprint 7.4: stock documents (SR/SI/ST). Read shape + raw input shape,
# same split as apps.vouchers.serializers (VoucherSerializer /
# VoucherCreateSerializer): every output total is computed server-side,
# no total is ever accepted as input.
# ---------------------------------------------------------------------


class StockDocumentLineSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source="item.name", read_only=True)
    item_sku = serializers.CharField(source="item.sku", read_only=True)
    uom_name = serializers.CharField(source="uom.name_ar", read_only=True, default=None)
    cost_center_name = serializers.CharField(source="cost_center.name", read_only=True, default=None)
    batch_number = serializers.CharField(source="batch.number", read_only=True, default=None)
    batch_expiry = serializers.DateField(source="batch.expiry", read_only=True, default=None)
    serial_numbers = serializers.SerializerMethodField()
    counted_serial_numbers = serializers.SerializerMethodField()
    item_tracking = serializers.CharField(source="item.tracking", read_only=True)

    class Meta:
        model = StockDocumentLine
        fields = (
            "id", "item", "item_name", "item_sku", "item_tracking", "uom", "uom_name", "qty", "qty_base", "unit_cost",
            "cost_center", "cost_center_name", "batch", "batch_number", "batch_expiry", "serial_numbers",
            "expected_qty", "counted_qty", "counted_serial_numbers", "surplus_unit_cost",
        )
        read_only_fields = fields

    def get_serial_numbers(self, obj):
        return [s.serial for s in obj.serials.all()]

    def get_counted_serial_numbers(self, obj):
        return [s.serial for s in obj.counted_serials.all()]


class StockDocumentSerializer(serializers.ModelSerializer):
    lines = StockDocumentLineSerializer(many=True, read_only=True)
    legal_entity_name = serializers.CharField(source="legal_entity.name", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    to_warehouse_name = serializers.CharField(source="to_warehouse.name", read_only=True, default=None)
    to_legal_entity = serializers.UUIDField(source="to_warehouse.legal_entity_id", read_only=True, default=None)
    to_legal_entity_name = serializers.CharField(source="to_warehouse.legal_entity.name", read_only=True, default=None)
    party_name = serializers.CharField(source="party.name", read_only=True, default=None)
    account_name = serializers.SerializerMethodField()
    total_qty = serializers.SerializerMethodField()
    total_value = serializers.SerializerMethodField()
    total_is_estimate = serializers.SerializerMethodField()
    transfer_received = serializers.SerializerMethodField()
    reversed_by_id = serializers.SerializerMethodField()
    journal_entries = serializers.SerializerMethodField()

    class Meta:
        model = StockDocument
        fields = (
            "id", "kind", "number", "date", "status", "legal_entity", "legal_entity_name",
            "warehouse", "warehouse_name", "to_warehouse", "to_warehouse_name", "to_legal_entity",
            "to_legal_entity_name", "party", "party_name", "account", "account_name", "reference", "notes",
            "reverses", "reversed_by_id", "created_by", "created_at", "count_scope", "lines",
            "total_qty", "total_value", "total_is_estimate", "transfer_received", "journal_entries",
        )
        read_only_fields = fields

    def _totals(self, obj):
        from .services import document_totals

        cache = self.context.setdefault("_totals", {})
        if obj.id not in cache:
            cache[obj.id] = document_totals(obj)
        return cache[obj.id]

    def get_account_name(self, obj):
        return f"{obj.account.code} — {obj.account.name}" if obj.account_id else None

    def get_total_qty(self, obj):
        return str(self._totals(obj)["total_qty"])

    def get_total_value(self, obj):
        return str(self._totals(obj)["total_value"])

    def get_total_is_estimate(self, obj):
        return self._totals(obj)["is_estimate"]

    def get_transfer_received(self, obj):
        from .services import _transfer_received

        return obj.kind == "transfer" and _transfer_received(obj)

    def get_reversed_by_id(self, obj):
        reversal = obj.reversed_by.only("id").first()
        return str(reversal.id) if reversal else None

    def get_journal_entries(self, obj):
        from django.contrib.contenttypes.models import ContentType

        from apps.accounting.models import JournalEntry

        rows = JournalEntry.objects.filter(
            content_type=ContentType.objects.get_for_model(type(obj)), object_id=obj.id,
        ).order_by("date", "created_at").values("id", "number", "date")
        return [{"id": str(r["id"]), "number": r["number"], "date": r["date"]} for r in rows]


class StockDocumentLineInputSerializer(serializers.Serializer):
    item = serializers.UUIDField()
    uom = serializers.UUIDField(required=False, allow_null=True)
    qty = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    unit_cost = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True, min_value=Decimal("0")
    )
    cost_center = serializers.UUIDField(required=False, allow_null=True)
    batch = serializers.UUIDField(required=False, allow_null=True)
    batch_number = serializers.CharField(required=False, allow_blank=True, max_length=50)
    batch_expiry = serializers.DateField(required=False, allow_null=True)
    serials = serializers.ListField(child=serializers.CharField(max_length=100), required=False, default=list)


class StockDocumentInputSerializer(serializers.Serializer):
    """Create (all fields) and draft edit (partial). `kind` is fixed at
    creation — an edit can't turn a receipt into an issue."""

    kind = serializers.ChoiceField(
        choices=[("receipt", "receipt"), ("issue", "issue"), ("transfer", "transfer"), ("count", "count")]
    )
    legal_entity = serializers.PrimaryKeyRelatedField(queryset=LegalEntity.objects.none())
    warehouse = serializers.PrimaryKeyRelatedField(queryset=Warehouse.objects.none())
    to_warehouse = serializers.PrimaryKeyRelatedField(queryset=Warehouse.objects.none(), required=False, allow_null=True)
    date = serializers.DateField()
    party = serializers.PrimaryKeyRelatedField(queryset=Account.objects.none(), required=False, allow_null=True)
    account = serializers.PrimaryKeyRelatedField(queryset=Account.objects.none(), required=False, allow_null=True)
    reference = serializers.CharField(required=False, allow_blank=True, default="", max_length=100)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    lines = StockDocumentLineInputSerializer(many=True, required=False)
    # kind=count only: the partial-count scope. Lines are never sent for a
    # count — the session fills them from the warehouse's balances.
    category = serializers.PrimaryKeyRelatedField(queryset=Account.objects.none(), required=False, allow_null=True)
    search = serializers.CharField(required=False, allow_blank=True, default="", max_length=100)

    def validate(self, attrs):
        if attrs.get("kind") == "count":
            if attrs.get("lines"):
                raise serializers.ValidationError({"lines": ["أسطر جلسة الجرد تُملأ من الأرصدة — لا تُرسل."]})
        elif "lines" not in attrs and not self.partial:
            raise serializers.ValidationError({"lines": [_("This field is required.")]})
        return attrs

    def __init__(self, *args, **kwargs):
        from apps.organization.services import get_accessible_entity_ids
        from apps.parties.models import Party

        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            tenant = request.user.tenant
            accessible = get_accessible_entity_ids(request.user)
            self.fields["legal_entity"].queryset = LegalEntity.objects.filter(tenant=tenant, id__in=accessible)
            self.fields["warehouse"].queryset = Warehouse.objects.filter(
                tenant=tenant, legal_entity_id__in=accessible, deleted_at__isnull=True, is_active=True,
            )
            # The destination may be a branch this user can't otherwise
            # see — sending stock there is the source branch's act; the
            # destination confirms it on its own side.
            self.fields["to_warehouse"].queryset = Warehouse.objects.filter(
                tenant=tenant, deleted_at__isnull=True, is_active=True,
            )
            self.fields["party"].queryset = Party.objects.filter(tenant=tenant)
            self.fields["account"].queryset = Account.objects.filter(tenant=tenant)
            self.fields["category"].queryset = ItemCategory.objects.filter(tenant=tenant, deleted_at__isnull=True)


class CountEntrySerializer(serializers.Serializer):
    line = serializers.IntegerField()
    counted_qty = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=30)
    serials = serializers.ListField(child=serializers.CharField(max_length=100), required=False, default=list)


class CountEntriesSerializer(serializers.Serializer):
    entries = CountEntrySerializer(many=True)


class SurplusCostEntrySerializer(serializers.Serializer):
    line = serializers.IntegerField()
    unit_cost = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=30)


class SurplusCostsSerializer(serializers.Serializer):
    entries = SurplusCostEntrySerializer(many=True)


class StockDocumentReasonSerializer(serializers.Serializer):
    """reverse (reason required) / confirm-receipt (no reason) — both take
    an optional effective date; the engine defaults it to today."""

    reason = serializers.CharField(required=False, allow_blank=True, default="")
    date = serializers.DateField(required=False, allow_null=True)

    def validate(self, attrs):
        if not self.context.get("reason_optional") and len(attrs.get("reason", "").strip()) < 3:
            raise serializers.ValidationError({"reason": [_("A reason is required to reverse a stock document.")]})
        return attrs


class StockLevelSerializer(serializers.ModelSerializer):
    """Sprint 7.4: «أرصدة المخزون» — read-only. avg_cost is the item's
    company-wide moving average (D2); value = qty x that average, so a
    warehouse's value is its share of the company total, not a separate
    valuation."""

    item_name = serializers.CharField(source="item.name", read_only=True)
    item_sku = serializers.CharField(source="item.sku", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    legal_entity = serializers.UUIDField(source="warehouse.legal_entity_id", read_only=True)
    legal_entity_name = serializers.CharField(source="warehouse.legal_entity.name", read_only=True)
    avg_cost = serializers.DecimalField(max_digits=14, decimal_places=4, read_only=True)
    value = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = StockLevel
        fields = (
            "id", "item", "item_name", "item_sku", "warehouse", "warehouse_name", "legal_entity",
            "legal_entity_name", "qty_on_hand", "qty_reserved", "avg_cost", "value",
        )
        read_only_fields = fields
