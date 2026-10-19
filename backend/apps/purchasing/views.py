from rest_framework import filters
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access.permissions import HasModulePermission, RequiresModuleFeature
from apps.common.viewsets import TenantScopedViewSet

from .models import PurchaseSettings, WithholdingTaxCode
from .serializers import PurchaseSettingsSerializer, WithholdingTaxCodeSerializer


class PurchaseSettingsView(APIView):
    """GET/PATCH the authenticated user's own tenant's purchase settings
    (R-8.5 tolerances, GRNI policy) — one row per tenant, created lazily,
    same shape as apps.inventory.views.InventorySettingsView. Gated on
    TenantFeatures.purchasing: a tenant without the module gets a 404."""

    permission_classes = [IsAuthenticated, RequiresModuleFeature, HasModulePermission]
    permission_map = {"view": "purchasing.view", "manage": "purchasing.manage"}
    module_feature = "purchasing"

    def get(self, request):
        settings_obj, _created = PurchaseSettings.objects.get_or_create(tenant=request.user.tenant)
        return Response(PurchaseSettingsSerializer(settings_obj).data)

    def patch(self, request):
        settings_obj, _created = PurchaseSettings.objects.get_or_create(tenant=request.user.tenant)
        serializer = PurchaseSettingsSerializer(settings_obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class WithholdingTaxCodeViewSet(TenantScopedViewSet):
    """Sprint 8.0 (D6): the tenant's withholding codes, read-only. They
    come only from apps/compliance/<country>/withholding.json
    (load_withholding_codes); approving or editing them is 8.3's settings
    screen, not this block's."""

    queryset = WithholdingTaxCode.objects.all()
    serializer_class = WithholdingTaxCodeSerializer
    permission_classes = [IsAuthenticated, RequiresModuleFeature, HasModulePermission]
    module_feature = "purchasing"
    permission_map = {"list": "purchasing.view", "retrieve": "purchasing.view"}
    http_method_names = ["get", "head", "options"]
    filter_backends = [filters.SearchFilter]
    search_fields = ["code", "name_ar"]
