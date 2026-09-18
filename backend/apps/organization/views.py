from django.db.models import Q
from rest_framework import filters
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.access.permissions import HasModulePermission
from apps.common.viewsets import SoftDeleteViewSetMixin, TenantScopedViewSet

from .models import CostCenter, LegalEntity
from .serializers import (
    CostCenterSerializer,
    CostCenterTreeSerializer,
    LegalEntitySerializer,
    LegalEntityTreeSerializer,
)
from .services import get_accessible_entity_ids


class LegalEntityViewSet(SoftDeleteViewSetMixin, TenantScopedViewSet):
    serializer_class = LegalEntitySerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = LegalEntity.objects.all()
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["code", "name"]
    ordering_fields = ["code", "name", "created_at"]
    permission_map = {
        "list": "organization.view",
        "retrieve": "organization.view",
        "tree": "organization.view",
        "create": "organization.manage",
        "update": "organization.manage",
        "partial_update": "organization.manage",
        "destroy": "organization.manage",
        "deactivate": "organization.manage",
        "activate": "organization.manage",
    }

    def get_queryset(self):
        accessible_ids = get_accessible_entity_ids(self.request.user)
        return super().get_queryset().filter(id__in=accessible_ids)

    @action(detail=False, methods=["get"])
    def tree(self, request):
        accessible_ids = get_accessible_entity_ids(request.user)
        roots = (
            LegalEntity.objects.filter(tenant=request.user.tenant, id__in=accessible_ids)
            .filter(Q(parent__isnull=True) | ~Q(parent_id__in=accessible_ids))
            .order_by("code")
        )
        serializer = LegalEntityTreeSerializer(
            roots, many=True, context={"visible_ids": accessible_ids, "request": request}
        )
        return Response(serializer.data)


class CostCenterViewSet(SoftDeleteViewSetMixin, TenantScopedViewSet):
    serializer_class = CostCenterSerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = CostCenter.objects.all()
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["code", "name"]
    ordering_fields = ["code", "name", "created_at"]
    permission_map = {
        "list": "costcenters.view",
        "retrieve": "costcenters.view",
        "tree": "costcenters.view",
        "create": "costcenters.manage",
        "update": "costcenters.manage",
        "partial_update": "costcenters.manage",
        "destroy": "costcenters.manage",
        "deactivate": "costcenters.manage",
        "activate": "costcenters.manage",
    }

    @action(detail=False, methods=["get"])
    def tree(self, request):
        roots = CostCenter.objects.filter(tenant=request.user.tenant, parent__isnull=True).order_by(
            "code"
        )
        return Response(CostCenterTreeSerializer(roots, many=True).data)
