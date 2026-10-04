from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access.permissions import HasModulePermission, RequiresModuleFeature

from .models import InventorySettings
from .serializers import InventorySettingsSerializer


class InventorySettingsView(APIView):
    """GET/PATCH the authenticated user's own tenant's inventory
    settings — one row per tenant (apps.inventory.models.
    InventorySettings), created lazily on first access, same shape as
    apps.numbering's own DocumentNumberingSetting viewset. The first
    real endpoint under /api/inventory/* — also the one the module
    gate (RequiresModuleFeature) and the 404-for-a-tenant-without-the-
    module test exercise."""

    # RequiresModuleFeature before HasModulePermission: a disabled
    # module must 404 for EVERY user, not just one who also happens to
    # lack inventory.view — permission ordering is evaluation order in
    # DRF, and the first False/raise wins.
    permission_classes = [IsAuthenticated, RequiresModuleFeature, HasModulePermission]
    permission_map = {"view": "inventory.view", "manage": "inventory.manage"}
    module_feature = "inventory"

    def get(self, request):
        settings_obj, _created = InventorySettings.objects.get_or_create(tenant=request.user.tenant)
        return Response(InventorySettingsSerializer(settings_obj).data)

    def patch(self, request):
        settings_obj, _created = InventorySettings.objects.get_or_create(tenant=request.user.tenant)
        serializer = InventorySettingsSerializer(settings_obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
