from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.accounting.models import Account
from apps.sales.models import Product

from .models import InventorySettings, ItemBarcode, ItemCategory, ItemUoM, UnitOfMeasure


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
