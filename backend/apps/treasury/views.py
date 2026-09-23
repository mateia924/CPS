import datetime

from django.core.exceptions import PermissionDenied, ValidationError
from rest_framework import filters, mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.access.permissions import HasModulePermission
from apps.accounting.services import get_or_create_treasury_account, ledger_lines
from apps.common.viewsets import SoftDeleteViewSetMixin, TenantScopedViewSet

from .models import (
    Bank,
    BankStatement,
    BankStatementLine,
    CashBox,
    Custody,
    ExchangeRate,
    IbanChangeRequest,
)
from .reconciliation import find_candidates, ignore_line, manual_match, unmatch
from .serializers import (
    BankSerializer,
    BankStatementLineSerializer,
    BankStatementListSerializer,
    BankStatementSerializer,
    CashBoxSerializer,
    CustodySerializer,
    ExchangeRateSerializer,
    IbanChangeRequestCreateSerializer,
    IbanChangeRequestSerializer,
    IgnoreStatementLineSerializer,
    MatchStatementLineSerializer,
    StatementImportSerializer,
)
from .services import (
    TreasuryConflictError,
    approve_iban_change_request,
    create_iban_change_request,
    import_bank_statement,
    reject_iban_change_request,
    submit_iban_change_request,
    withdraw_iban_change_request,
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


class IbanChangeRequestViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    """الإعدادات ← "طلبات تغيير IBAN" (3.15.9, sprint 5.5 block 5.5.0).
    `create` only ever builds a DRAFT (no attachment required yet); the
    IBAN letter attachment (3.17) is required by `submit`, not here —
    same two-step shape as every other document that needs an
    AttachmentPanel before it can move."""

    serializer_class = IbanChangeRequestSerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = IbanChangeRequest.objects.all()
    permission_map = {
        "list": "treasury.request_iban_change",
        "retrieve": "treasury.request_iban_change",
        "create": "treasury.request_iban_change",
        "submit": "treasury.request_iban_change",
        "withdraw": "treasury.request_iban_change",
        "approve": "treasury.request_iban_change",
        "reject": "treasury.request_iban_change",
    }

    def get_queryset(self):
        queryset = super().get_queryset().filter(tenant=self.request.user.tenant)
        status_param = self.request.query_params.get("status")
        if status_param:
            queryset = queryset.filter(status=status_param)
        return queryset

    def create(self, request, *args, **kwargs):
        serializer = IbanChangeRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            iban_request = create_iban_change_request(
                tenant=request.user.tenant, user=request.user,
                target_type=data["target_type"], target_id=data["target_id"],
                new_iban=data["new_iban"], reason=data["reason"],
            )
        except ValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else {"detail": str(exc)}
            return Response(detail, status=400)
        return Response(IbanChangeRequestSerializer(iban_request).data, status=201)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        iban_request = self.get_object()
        try:
            submit_iban_change_request(iban_request, request.user, request=request)
        except ValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else {"detail": str(exc)}
            return Response(detail, status=400)
        return Response(IbanChangeRequestSerializer(iban_request).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        iban_request = self.get_object()
        try:
            approve_iban_change_request(iban_request, request.user, request=request)
        except ValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else {"detail": str(exc)}
            return Response(detail, status=400)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=403)
        return Response(IbanChangeRequestSerializer(iban_request).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        iban_request = self.get_object()
        reason = request.data.get("reason", "")
        try:
            reject_iban_change_request(iban_request, request.user, reason, request=request)
        except ValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else {"detail": str(exc)}
            return Response(detail, status=400)
        return Response(IbanChangeRequestSerializer(iban_request).data)

    @action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        iban_request = self.get_object()
        try:
            withdraw_iban_change_request(iban_request, request.user, request=request)
        except ValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else {"detail": str(exc)}
            return Response(detail, status=400)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=403)
        return Response(IbanChangeRequestSerializer(iban_request).data)


class BankStatementViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """`GET /api/bank-statements/?bank=<id>` (list, filtered per bank —
    same `?party=`/`?employee=` filter pattern as VoucherViewSet/
    CustodyViewSet), `GET /api/bank-statements/{id}/` (detail with
    lines), `POST /api/bank-statements/import/` (block 5.5.1). Never
    created via the generic DRF `create` — always through `import_`."""

    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = BankStatement.objects.all()
    permission_map = {
        "list": "treasury.view",
        "retrieve": "treasury.view",
        "import_": "treasury.reconcile",
    }

    def get_serializer_class(self):
        return BankStatementListSerializer if self.action == "list" else BankStatementSerializer

    def get_queryset(self):
        queryset = super().get_queryset().filter(tenant=self.request.user.tenant)
        bank_id = self.request.query_params.get("bank")
        if bank_id:
            queryset = queryset.filter(bank_id=bank_id)
        return queryset.select_related("bank", "imported_by")

    @action(detail=False, methods=["post"], url_path="import")
    def import_(self, request):
        serializer = StatementImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            bank = Bank.objects.get(tenant=request.user.tenant, id=request.data.get("bank"))
        except (Bank.DoesNotExist, ValueError, TypeError):
            return Response({"bank": ["Bank not found."]}, status=404)

        try:
            statement, auto_matched, unmatched, warnings = import_bank_statement(
                tenant=request.user.tenant, user=request.user, bank=bank, file_obj=data["file"],
                import_format=data["import_format"], period_start=data["period_start"],
                period_end=data["period_end"], opening_balance=data["opening_balance"],
                closing_balance=data["closing_balance"], currency=data.get("currency") or bank.currency,
                column_mapping=data.get("column_mapping"), request=request,
            )
        except TreasuryConflictError as exc:
            return Response({"detail": str(exc.message)}, status=409)
        except ValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else {"detail": str(exc)}
            return Response(detail, status=400)

        payload = BankStatementSerializer(statement).data
        payload["auto_matched"] = auto_matched
        payload["unmatched"] = unmatched
        payload["warnings"] = warnings
        return Response(payload, status=201)


class BankStatementLineViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """`POST /api/statement-lines/{id}/match/`, `unmatch/`, `ignore/`,
    `GET .../candidates/` — block 5.5.2. Lines are only ever reached
    through a statement's own list (`BankStatementSerializer.lines`);
    this ViewSet exists purely to host the matching actions."""

    serializer_class = BankStatementLineSerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = BankStatementLine.objects.all()
    permission_map = {
        "retrieve": "treasury.view",
        "candidates": "treasury.view",
        "match": "treasury.reconcile",
        "unmatch": "treasury.reconcile",
        "ignore": "treasury.reconcile",
    }

    def get_queryset(self):
        return super().get_queryset().filter(tenant=self.request.user.tenant)

    @action(detail=True, methods=["get"])
    def candidates(self, request, pk=None):
        line = self.get_object()
        candidates = find_candidates(line)
        return Response(
            [
                {
                    "id": str(c.id), "date": c.entry.date, "entry_id": str(c.entry_id),
                    "entry_number": c.entry.number, "description": c.description or c.entry.memo,
                    "debit_fc": str(c.debit_fc), "credit_fc": str(c.credit_fc),
                }
                for c in candidates
            ]
        )

    @action(detail=True, methods=["post"])
    def match(self, request, pk=None):
        line = self.get_object()
        serializer = MatchStatementLineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            manual_match(line, serializer.validated_data["journal_line_ids"], request.user, request=request)
        except ValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else {"detail": str(exc)}
            return Response(detail, status=400)
        return Response(BankStatementLineSerializer(line).data)

    @action(detail=True, methods=["post"])
    def unmatch(self, request, pk=None):
        line = self.get_object()
        unmatch(line, request.user, request=request)
        return Response(BankStatementLineSerializer(line).data)

    @action(detail=True, methods=["post"])
    def ignore(self, request, pk=None):
        line = self.get_object()
        serializer = IgnoreStatementLineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            ignore_line(line, serializer.validated_data["reason"], request.user, request=request)
        except ValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else {"detail": str(exc)}
            return Response(detail, status=400)
        return Response(BankStatementLineSerializer(line).data)
