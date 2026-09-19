from rest_framework import filters
from rest_framework.permissions import IsAuthenticated

from apps.access.permissions import HasModulePermission
from apps.common.viewsets import SoftDeleteViewSetMixin, TenantScopedViewSet

from .models import Bank, CashBox, Custody
from .serializers import BankSerializer, CashBoxSerializer, CustodySerializer

_PERMISSION_MAP = {
    "list": "treasury.view",
    "retrieve": "treasury.view",
    "create": "treasury.manage",
    "update": "treasury.manage",
    "partial_update": "treasury.manage",
    "destroy": "treasury.manage",
    "deactivate": "treasury.manage",
    "activate": "treasury.manage",
}


class BankViewSet(SoftDeleteViewSetMixin, TenantScopedViewSet):
    serializer_class = BankSerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = Bank.objects.all()
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "bank_name", "account_number", "iban"]
    ordering_fields = ["name", "created_at"]
    permission_map = _PERMISSION_MAP


class CashBoxViewSet(SoftDeleteViewSetMixin, TenantScopedViewSet):
    serializer_class = CashBoxSerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = CashBox.objects.all()
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name"]
    ordering_fields = ["name", "created_at"]
    permission_map = _PERMISSION_MAP


class CustodyViewSet(SoftDeleteViewSetMixin, TenantScopedViewSet):
    serializer_class = CustodySerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = Custody.objects.all()
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name"]
    ordering_fields = ["name", "created_at"]
    permission_map = _PERMISSION_MAP
