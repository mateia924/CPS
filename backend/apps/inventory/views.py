from rest_framework import filters
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access.permissions import HasModulePermission, RequiresModuleFeature
from apps.common.viewsets import EntityScopedViewSet, SoftDeleteViewSetMixin, TenantScopedViewSet
from apps.tenants.services import TenantLimitExceeded, check_warehouse_limit

from .models import (
    InventorySettings,
    ItemBarcode,
    ItemCategory,
    ItemUoM,
    UnitOfMeasure,
    Warehouse,
    set_default_warehouse,
)
from .serializers import (
    InventorySettingsSerializer,
    ItemBarcodeSerializer,
    ItemCategorySerializer,
    ItemUoMSerializer,
    UnitOfMeasureSerializer,
    WarehouseSerializer,
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


class WarehouseViewSet(SoftDeleteViewSetMixin, EntityScopedViewSet):
    """Sprint 7.2 (block spec, item 1). Gated by the "inventory" module
    (unlike ItemCategory/UnitOfMeasure/ItemBarcode above, which are
    "products" — a warehouse only makes sense once a tenant has
    actually turned inventory on)."""

    serializer_class = WarehouseSerializer
    permission_classes = [IsAuthenticated, RequiresModuleFeature, HasModulePermission]
    module_feature = "inventory"
    queryset = Warehouse.objects.all()
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["code", "name"]
    ordering_fields = ["code", "created_at"]
    permission_map = {
        "list": "inventory.view",
        "retrieve": "inventory.view",
        "create": "inventory.manage",
        "update": "inventory.manage",
        "partial_update": "inventory.manage",
        "destroy": "inventory.manage",
        "deactivate": "inventory.manage",
        "activate": "inventory.manage",
        "set_default": "inventory.manage",
    }

    def get_queryset(self):
        qs = super().get_queryset()
        # 6.6.1/4: the warehouse screen's own entity column + an
        # explicit "all" filter — same optional, never-silent-default
        # query param shape as BankViewSet's own legal_entity filter.
        legal_entity_id = self.request.query_params.get("legal_entity")
        if legal_entity_id:
            qs = qs.filter(legal_entity_id=legal_entity_id)
        return qs

    def create(self, request, *args, **kwargs):
        try:
            check_warehouse_limit(request.user.tenant)
        except TenantLimitExceeded as exc:
            return Response({"detail": exc.message}, status=402)
        return super().create(request, *args, **kwargs)

    @action(detail=True, methods=["post"], url_path="set-default")
    def set_default(self, request, pk=None):
        """The one, deliberate "تبديل ذرّي" (atomic switch) action —
        unsets whatever was this warehouse's entity's old default and
        sets this one, in a single transaction (apps.inventory.models.
        set_default_warehouse). The normal create/update path refuses
        (400) to set is_default=True while a different warehouse is
        already default for that entity — this action is the only way
        to actually change it."""
        warehouse = self.get_object()
        set_default_warehouse(warehouse)
        return Response(self.get_serializer(warehouse).data)
