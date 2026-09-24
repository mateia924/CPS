from rest_framework import serializers

from .models import TenantFeatures


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
