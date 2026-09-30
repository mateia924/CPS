from django.utils.translation import gettext_lazy as _
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
        # Sprint 6.6.2 (item 1): "إعداد على المستأجر require_2fa_for_
        # roles" — same Owner-only PATCH screen, validated against the
        # tenant's own RBAC role names below.
        fields = ("default_legal_entity", "require_2fa_for_roles")

    def validate_require_2fa_for_roles(self, value):
        from apps.access.models import Role

        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise serializers.ValidationError(_("A list of role names is required."))
        tenant = self.context["request"].user.tenant
        valid_names = set(Role.objects.filter(tenant=tenant).values_list("name", flat=True))
        unknown = set(value) - valid_names
        if unknown:
            raise serializers.ValidationError(
                _("Unknown role name(s): %(names)s") % {"names": ", ".join(sorted(unknown))}
            )
        return value

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.organization.models import LegalEntity

        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            self.fields["default_legal_entity"].queryset = LegalEntity.objects.filter(
                tenant=request.user.tenant, is_active=True
            )
