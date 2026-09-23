import datetime

from rest_framework import filters
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.access.permissions import HasModulePermission
from apps.accounting.services import get_or_create_treasury_account, ledger_lines
from apps.common.viewsets import SoftDeleteViewSetMixin, TenantScopedViewSet

from .models import Bank, CashBox, Custody, ExchangeRate
from .serializers import (
    BankSerializer,
    CashBoxSerializer,
    CustodySerializer,
    ExchangeRateSerializer,
)

_PERMISSION_MAP = {
    "list": "treasury.view",
    "retrieve": "treasury.view",
    "create": "treasury.manage",
    "update": "treasury.manage",
    "partial_update": "treasury.manage",
    "destroy": "treasury.manage",
    "deactivate": "treasury.manage",
    "activate": "treasury.manage",
    "movements": "treasury.view",
}


class _TreasuryMovementsMixin:
    """Sprint 5.4 (docs/prompts/sprint-5.md block 5.4): "الحركات" tab on
    the bank/cash-box/custody detail screen — one thin wrapper per
    ViewSet around the shared `ledger_lines()` service, on the
    instance's own `gl_account` (auto-provisioned by
    `get_or_create_treasury_account` at create time)."""

    @action(detail=True, methods=["get"])
    def movements(self, request, pk=None):
        instance = self.get_object()
        if instance.gl_account_id is None:
            return Response({"opening_balance": "0", "opening_balance_fc": "0", "lines": [], "closing_balance": "0", "closing_balance_fc": "0"})
        date_from = request.query_params.get("from")
        date_to = request.query_params.get("to")
        result = ledger_lines(
            request.user.tenant, instance.gl_account,
            date_from=datetime.date.fromisoformat(date_from) if date_from else None,
            date_to=datetime.date.fromisoformat(date_to) if date_to else None,
        )
        return Response(result)


class BankViewSet(_TreasuryMovementsMixin, SoftDeleteViewSetMixin, TenantScopedViewSet):
    serializer_class = BankSerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = Bank.objects.all()
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "bank_name", "account_number", "iban"]
    ordering_fields = ["name", "created_at"]
    permission_map = _PERMISSION_MAP

    def perform_create(self, serializer):
        super().perform_create(serializer)
        get_or_create_treasury_account(serializer.instance, "BANKS")


class CashBoxViewSet(_TreasuryMovementsMixin, SoftDeleteViewSetMixin, TenantScopedViewSet):
    serializer_class = CashBoxSerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = CashBox.objects.all()
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name"]
    ordering_fields = ["name", "created_at"]
    permission_map = _PERMISSION_MAP

    def perform_create(self, serializer):
        super().perform_create(serializer)
        get_or_create_treasury_account(serializer.instance, "CASH")


class CustodyViewSet(_TreasuryMovementsMixin, SoftDeleteViewSetMixin, TenantScopedViewSet):
    serializer_class = CustodySerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = Custody.objects.all()
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name"]
    ordering_fields = ["name", "created_at"]
    permission_map = _PERMISSION_MAP

    def perform_create(self, serializer):
        super().perform_create(serializer)
        get_or_create_treasury_account(serializer.instance, "CUSTODIES")

    def get_queryset(self):
        queryset = super().get_queryset()
        # Sprint 3.5: backs the employee detail screen's "عُهده" list.
        employee_id = self.request.query_params.get("employee")
        if employee_id:
            queryset = queryset.filter(employee_id=employee_id)
        return queryset


class ExchangeRateViewSet(TenantScopedViewSet):
    """الخزينة ← "أسعار الصرف" (3.15.3): جدول + إضافة فقط — لا
    تعديل/حذف، سجل تاريخي لا يُصحَّح إلا بإضافة سطر جديد (نفس مبدأ عدم
    تعديل قيد مُرحَّل)."""

    http_method_names = ["get", "post", "head", "options"]
    serializer_class = ExchangeRateSerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = ExchangeRate.objects.all()
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["date", "created_at"]
    permission_map = {
        "list": "treasury.view",
        "retrieve": "treasury.view",
        "create": "treasury.manage",
    }

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.user.tenant, created_by=self.request.user)
