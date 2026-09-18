from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from .models import Account, JournalEntry
from .serializers import AccountSerializer, JournalEntrySerializer


class AccountViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only chart of accounts — accounts are seeded per tenant at
    registration; editing the chart is out of scope for this phase."""

    serializer_class = AccountSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Account.objects.filter(tenant=self.request.user.tenant)


class JournalEntryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = JournalEntrySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            JournalEntry.objects.filter(tenant=self.request.user.tenant)
            .prefetch_related("lines", "lines__account")
        )
