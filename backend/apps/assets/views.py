from rest_framework import filters
from rest_framework.permissions import IsAuthenticated

from apps.access.permissions import HasModulePermission
from apps.common.viewsets import SoftDeleteViewSetMixin, TenantScopedViewSet

from .models import Asset
from .serializers import AssetSerializer


class AssetViewSet(SoftDeleteViewSetMixin, TenantScopedViewSet):
    serializer_class = AssetSerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = Asset.objects.all()
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["code", "name"]
    ordering_fields = ["code", "name", "purchase_date", "created_at"]
    permission_map = {
        "list": "assets.view",
        "retrieve": "assets.view",
        "create": "assets.manage",
        "update": "assets.manage",
        "partial_update": "assets.manage",
        "destroy": "assets.manage",
        "deactivate": "assets.manage",
        "activate": "assets.manage",
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        # Sprint 3.5: backs the employee detail screen's "أصوله المحفوظة
        # عنده" list.
        custodian_id = self.request.query_params.get("custodian")
        if custodian_id:
            queryset = queryset.filter(custodian_id=custodian_id)
        return queryset
