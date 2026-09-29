from rest_framework import serializers

from .models import Tenant, TenantFeatures


class TenantFeaturesSerializer(serializers.ModelSerializer):
    """Sprint 6.8 (decisions 16/19): الإعدادات ← الشركة — only these two
    are ever tenant-editable; every other flag is plan-driven
    (apps.tenants.services.apply_plan_to_tenant) and stays read-only
    here."""

    class Meta:
        model = TenantFeatures
        fields = (
            "organization", "cost_centers", "inventory", "purchasing", "hr", "treasury", "assets",
            "credit_limit_mode", "cost_center_required",
        )
        read_only_fields = ("organization", "cost_centers", "inventory", "purchasing", "hr", "treasury", "assets")


class TenantSettingsSerializer(serializers.ModelSerializer):
    """Sprint 6.5.14: الإعدادات ← الشركة ← متقدم — «الكيان الافتراضي
    للمستندات» (Tenant.default_legal_entity). Same Owner-only PATCH
    pattern as TenantFeaturesSerializer above, its own tiny serializer
    since the field lives on Tenant, not TenantFeatures."""

    class Meta:
        model = Tenant
        fields = ("default_legal_entity",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.organization.models import LegalEntity

        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            self.fields["default_legal_entity"].queryset = LegalEntity.objects.filter(
                tenant=request.user.tenant, is_active=True
            )
