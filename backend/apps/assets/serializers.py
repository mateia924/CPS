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
        )
        read_only_fields = ("id", "created_at")

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
