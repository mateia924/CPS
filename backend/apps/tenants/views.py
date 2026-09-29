from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import TenantFeatures
from .serializers import TenantFeaturesSerializer, TenantSettingsSerializer


class TenantFeaturesView(APIView):
    """Sprint 6.8 (decisions 16/19): الإعدادات ← الشركة — the tenant's
    own policy switches (credit_limit_mode, cost_center_required).
    Singleton per tenant, GET for everyone, PATCH for the Owner only
    (a company-wide policy change, not routine data entry)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        features, _created = TenantFeatures.objects.get_or_create(tenant_id=request.user.tenant_id)
        return Response(TenantFeaturesSerializer(features).data)

    def patch(self, request):
        from apps.access.services import user_is_owner

        if not user_is_owner(request.user):
            raise PermissionDenied()
        features, _created = TenantFeatures.objects.get_or_create(tenant_id=request.user.tenant_id)
        serializer = TenantFeaturesSerializer(features, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        from apps.common.viewsets import log_master_data_change, model_field_snapshot

        log_master_data_change(request, instance, "updated", after=model_field_snapshot(instance))
        return Response(TenantFeaturesSerializer(instance).data)


class TenantSettingsView(APIView):
    """Sprint 6.5.14: الإعدادات ← الشركة ← متقدم — «الكيان الافتراضي
    للمستندات» (Tenant.default_legal_entity). Same singleton/Owner-only
    shape as TenantFeaturesView above — a company-wide default, not
    routine data entry."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(TenantSettingsSerializer(request.user.tenant, context={"request": request}).data)

    def patch(self, request):
        from apps.access.services import user_is_owner

        if not user_is_owner(request.user):
            raise PermissionDenied()
        tenant = request.user.tenant
        serializer = TenantSettingsSerializer(
            tenant, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        from apps.common.viewsets import log_master_data_change, model_field_snapshot

        log_master_data_change(request, instance, "updated", after=model_field_snapshot(instance))
        return Response(TenantSettingsSerializer(instance, context={"request": request}).data)
