from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.access.permissions import HasModulePermission
from apps.common.viewsets import SoftDeleteViewSetMixin, TenantScopedViewSet
from apps.organization.services import get_accessible_entity_ids

from .models import Account, JournalEntry
from .serializers import AccountSerializer, AccountTreeSerializer, JournalEntrySerializer


class AccountViewSet(SoftDeleteViewSetMixin, TenantScopedViewSet):
    """دليل الحسابات (3.4/3.18): إضافة ابن، تعديل، تعطيل، بحث بالكود/
    الاسم. Sprint 4.3 — was read-only before this."""

    serializer_class = AccountSerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = Account.objects.all()
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["code", "name"]
    ordering_fields = ["code", "name", "created_at"]
    permission_map = {
        "list": "accounting.view",
        "retrieve": "accounting.view",
        "tree": "accounting.view",
        "create": "accounting.manage",
        "update": "accounting.manage",
        "partial_update": "accounting.manage",
        "destroy": "accounting.manage",
        "deactivate": "accounting.manage",
        "activate": "accounting.manage",
    }

    @action(detail=False, methods=["get"])
    def tree(self, request):
        roots = Account.objects.filter(tenant=request.user.tenant, parent__isnull=True).order_by("code")
        return Response(AccountTreeSerializer(roots, many=True).data)


class JournalEntryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = JournalEntrySerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    permission_map = {"list": "accounting.view", "retrieve": "accounting.view"}

    def get_queryset(self):
        accessible_ids = get_accessible_entity_ids(self.request.user)
        return (
            JournalEntry.objects.filter(
                tenant=self.request.user.tenant, legal_entity_id__in=accessible_ids
            )
            .prefetch_related("lines", "lines__account")
        )
