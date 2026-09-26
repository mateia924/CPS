from decimal import Decimal

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.organization.models import CostCenter, LegalEntity
from apps.organization.services import get_or_create_linked_cost_center
from apps.parties.models import Party, PartyRole

from .models import Asset


class AssetSerializer(serializers.ModelSerializer):
    # Write-only (3.3 section 4): "افتراضيًا مفعّل للسيارات" — only
    # meaningful when category == VEHICLE; ignored otherwise.
    create_linked_cost_center = serializers.BooleanField(required=False, default=True, write_only=True)

    class Meta:
        model = Asset
        fields = (
            "id", "legal_entity", "code", "name", "category", "purchase_date", "purchase_cost",
            "currency", "useful_life_months", "salvage_value", "depreciation_method",
            "custodian", "cost_center", "status", "is_active", "created_at",
            "create_linked_cost_center",
            # Sprint 6.5 (decisions 3, 4, 5, 9): writable.
            "is_depreciable", "purchase_reference", "in_service_date",
            "declining_balance_rate", "opening_accumulated_depreciation",
            # Sprint 6.5: read-only — frozen/computed by
            # apps.assets.depreciation, never set directly here.
            "cost_base", "salvage_base", "disposed_fraction", "depreciation_entry",
        )
        read_only_fields = ("id", "created_at", "cost_base", "salvage_base", "disposed_fraction", "depreciation_entry")

    def validate(self, attrs):
        # Sprint 6.5 (decision text under 6.5.0): "salvage_value <
        # purchase_cost، useful_life_months ≥ 1، declining_balance_rate
        # إلزامي فقط مع المتناقص وضمن (0، 100)" — a PATCH may omit any
        # of these, so fall back to the existing instance's value.
        def _value(name):
            return attrs.get(name, getattr(self.instance, name, None) if self.instance else None)

        purchase_cost = _value("purchase_cost")
        salvage_value = _value("salvage_value")
        if purchase_cost is not None and salvage_value is not None and salvage_value >= purchase_cost:
            raise serializers.ValidationError(
                {"salvage_value": [_("القيمة التخريدية يجب أن تكون أقل من تكلفة الشراء.")]}
            )

        useful_life_months = _value("useful_life_months")
        if useful_life_months is not None and useful_life_months < 1:
            raise serializers.ValidationError(
                {"useful_life_months": [_("العمر الإنتاجي يجب أن يكون شهرًا واحدًا على الأقل.")]}
            )

        method = _value("depreciation_method")
        rate = _value("declining_balance_rate")
        if method == Asset.DepreciationMethod.DECLINING_BALANCE:
            if rate is None:
                raise serializers.ValidationError(
                    {"declining_balance_rate": [_("معدّل الإهلاك المتناقص إلزامي مع هذه الطريقة.")]}
                )
            if not (Decimal("0") < rate < Decimal("100")):
                raise serializers.ValidationError(
                    {"declining_balance_rate": [_("معدّل الإهلاك المتناقص يجب أن يكون بين 0 و100.")]}
                )
        return attrs

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            tenant = request.user.tenant
            self.fields["legal_entity"].queryset = LegalEntity.objects.filter(tenant=tenant)
            self.fields["custodian"].queryset = Party.objects.filter(
                tenant=tenant, roles__role=PartyRole.Role.EMPLOYEE, roles__is_active=True
            )
            self.fields["cost_center"].queryset = CostCenter.objects.filter(tenant=tenant)

    def create(self, validated_data):
        create_linked = validated_data.pop("create_linked_cost_center", True)
        asset = super().create(validated_data)
        if create_linked and asset.category == Asset.Category.VEHICLE and asset.cost_center is None:
            linked = get_or_create_linked_cost_center(
                tenant=asset.tenant,
                linked_object=asset,
                code=f"CC-{asset.code}",
                name=asset.name,
                center_type=CostCenter.Type.VEHICLE,
            )
            asset.cost_center = linked
            asset.save(update_fields=["cost_center"])
        return asset

    def update(self, instance, validated_data):
        validated_data.pop("create_linked_cost_center", None)
        return super().update(instance, validated_data)
