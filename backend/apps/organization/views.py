from django.db.models import Q
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.access.permissions import HasModulePermission
from apps.common.viewsets import TenantScopedViewSet

from .models import CostCenter, LegalEntity
from .serializers import (
    CostCenterSerializer,
    CostCenterTreeSerializer,
    LegalEntitySerializer,
    LegalEntityTreeSerializer,
)
from .services import get_accessible_entity_ids


class LegalEntityViewSet(TenantScopedViewSet):
    serializer_class = LegalEntitySerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = LegalEntity.objects.all()
    permission_map = {
        "list": "organization.view",
        "retrieve": "organization.view",
        "tree": "organization.view",
        "create": "organization.manage",
        "update": "organization.manage",
        "partial_update": "organization.manage",
        "destroy": "organization.manage",
    }

    def get_queryset(self):
        accessible_ids = get_accessible_entity_ids(self.request.user)
        return super().get_queryset().filter(id__in=accessible_ids)

    def destroy(self, request, *args, **kwargs):
        # 3.1: "لا حذف لكيان عليه معاملات (soft-deactivate فقط)" — the
        # API never hard-deletes a legal entity, regardless of whether it
        # has transactions; it only deactivates it.
        entity = self.get_object()
        entity.is_active = False
        entity.save(update_fields=["is_active"])
        return Response(LegalEntitySerializer(entity).data)

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


class CostCenterViewSet(TenantScopedViewSet):
    serializer_class = CostCenterSerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = CostCenter.objects.all()
    permission_map = {
        "list": "costcenters.view",
        "retrieve": "costcenters.view",
        "tree": "costcenters.view",
        "create": "costcenters.manage",
        "update": "costcenters.manage",
        "partial_update": "costcenters.manage",
        "destroy": "costcenters.manage",
    }

    def destroy(self, request, *args, **kwargs):
        center = self.get_object()
        center.is_active = False
        center.save(update_fields=["is_active"])
        return Response(CostCenterSerializer(center).data)

    @action(detail=False, methods=["get"])
    def tree(self, request):
        roots = CostCenter.objects.filter(tenant=request.user.tenant, parent__isnull=True).order_by(
            "code"
        )
        return Response(CostCenterTreeSerializer(roots, many=True).data)
