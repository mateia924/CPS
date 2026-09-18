from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.access.permissions import HasModulePermission
from apps.organization.services import get_accessible_entity_ids

from .models import Account, JournalEntry
from .serializers import AccountSerializer, JournalEntrySerializer


class AccountViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only chart of accounts — accounts are seeded per tenant at
    registration; editing the chart is out of scope for this phase."""

    serializer_class = AccountSerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    permission_map = {"list": "accounting.view", "retrieve": "accounting.view"}

    def get_queryset(self):
        return Account.objects.filter(tenant=self.request.user.tenant)


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
