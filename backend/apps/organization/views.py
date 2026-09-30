from django.db.models import Q
from rest_framework import filters
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.access.permissions import HasModulePermission
from apps.common.viewsets import EntityScopedViewSet, SoftDeleteViewSetMixin, TenantScopedViewSet
from apps.tenants.services import TenantLimitExceeded, check_branch_limit

from .models import CostCenter, LegalEntity
from .serializers import (
    CostCenterSerializer,
    CostCenterTreeSerializer,
    LegalEntitySerializer,
    LegalEntityTreeSerializer,
)
from .services import get_accessible_entity_ids


class LegalEntityViewSet(SoftDeleteViewSetMixin, EntityScopedViewSet):
    # Sprint 6.6.1: the row being reached IS the entity, not a document
    # pointing at one — "id", not the mixin's own "legal_entity_id"
    # default.
    entity_lookup = "id"
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

    def create(self, request, *args, **kwargs):
        # Sprint 2 (3.14): plan's max_branches only limits BRANCH-type
        # nodes — holdings/companies are structural, not billable seats.
        if request.data.get("entity_type") == LegalEntity.Type.BRANCH:
            try:
                check_branch_limit(request.user.tenant)
            except TenantLimitExceeded as exc:
                return Response({"detail": exc.message}, status=402)
        return super().create(request, *args, **kwargs)

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
