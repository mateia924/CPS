from rest_framework import filters
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access.permissions import HasModulePermission, RequiresModuleFeature
from apps.common.viewsets import SoftDeleteViewSetMixin, TenantScopedViewSet

from .models import InventorySettings, ItemBarcode, ItemCategory, ItemUoM, UnitOfMeasure
from .serializers import (
    InventorySettingsSerializer,
    ItemBarcodeSerializer,
    ItemCategorySerializer,
    ItemUoMSerializer,
    UnitOfMeasureSerializer,
)


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


class ItemCategoryViewSet(SoftDeleteViewSetMixin, TenantScopedViewSet):
    """Sprint 7.1 (D7/D18). Part of the "products" module (available
    since sprint 1 — docs/catalog/modules.json), NOT gated behind
    RequiresModuleFeature("inventory") the way InventorySettingsView
    above is: a tenant with no warehouse/stock module at all can still
    want item categories (reusing the same `products.*` permission
    keys ProductViewSet already uses, not new ones)."""

    serializer_class = ItemCategorySerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = ItemCategory.objects.all()
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["code", "name"]
    ordering_fields = ["code", "name", "created_at"]
    permission_map = {
        "list": "products.view",
        "retrieve": "products.view",
        "create": "products.manage",
        "update": "products.manage",
        "partial_update": "products.manage",
        "destroy": "products.manage",
        "deactivate": "products.manage",
        "activate": "products.manage",
    }


class UnitOfMeasureViewSet(SoftDeleteViewSetMixin, TenantScopedViewSet):
    """Sprint 7.1 (D8)."""

    serializer_class = UnitOfMeasureSerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = UnitOfMeasure.objects.all()
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["code", "name_ar"]
    ordering_fields = ["code", "created_at"]
    permission_map = {
        "list": "products.view",
        "retrieve": "products.view",
        "create": "products.manage",
        "update": "products.manage",
        "partial_update": "products.manage",
        "destroy": "products.manage",
    }


class ItemUoMViewSet(SoftDeleteViewSetMixin, TenantScopedViewSet):
    """Sprint 7.1 (D8)."""

    serializer_class = ItemUoMSerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = ItemUoM.objects.all()
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["created_at"]
    permission_map = {
        "list": "products.view",
        "retrieve": "products.view",
        "create": "products.manage",
        "update": "products.manage",
        "partial_update": "products.manage",
        "destroy": "products.manage",
    }

    def get_queryset(self):
        qs = super().get_queryset()
        item_id = self.request.query_params.get("item")
        if item_id:
            qs = qs.filter(item_id=item_id)
        return qs


class ItemBarcodeViewSet(SoftDeleteViewSetMixin, TenantScopedViewSet):
    """Sprint 7.1 (D9)."""

    serializer_class = ItemBarcodeSerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = ItemBarcode.objects.all()
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["barcode"]
    ordering_fields = ["created_at"]
    permission_map = {
        "list": "products.view",
        "retrieve": "products.view",
        "create": "products.manage",
        "update": "products.manage",
        "partial_update": "products.manage",
        "destroy": "products.manage",
    }

    def get_queryset(self):
        qs = super().get_queryset()
        item_id = self.request.query_params.get("item")
        if item_id:
            qs = qs.filter(item_id=item_id)
        return qs
