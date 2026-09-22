from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from rest_framework import filters, mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.access.permissions import HasModulePermission
from apps.common.viewsets import SoftDeleteViewSetMixin, TenantScopedViewSet
from apps.organization.models import CostCenter
from apps.organization.services import get_accessible_entity_ids
from apps.treasury.services import ExchangeRateNotFound, get_rate

from .models import Account, JournalEntry
from .serializers import (
    AccountSerializer,
    AccountTreeSerializer,
    JournalEntryReverseSerializer,
    JournalEntrySerializer,
    ManualJournalEntryCreateSerializer,
)
from .services import (
    approve_journal_entry,
    compute_trial_balance,
    create_manual_journal_entry,
    post_journal_entry,
    reverse_journal_entry,
    submit_journal_entry_for_approval,
)


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


def _resolve_manual_lines(tenant, raw_lines):
    resolved = []
    for line in raw_lines:
        try:
            account = Account.objects.get(tenant=tenant, id=line["account"])
        except Account.DoesNotExist:
            raise ValidationError({"lines": ["Account not found."]})
        cost_center = None
        cost_center_id = line.get("cost_center")
        if cost_center_id:
            try:
                cost_center = CostCenter.objects.get(tenant=tenant, id=cost_center_id)
            except CostCenter.DoesNotExist:
                raise ValidationError({"lines": ["Cost center not found."]})
        resolved.append(
            {
                "account": account,
                "cost_center": cost_center,
                "description": line.get("description", ""),
                "debit_fc": line["debit_fc"],
                "credit_fc": line["credit_fc"],
            }
        )
    return resolved


class JournalEntryViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """القيود اليدوية (3.15.1/3.15.9) + القيود التلقائية (فواتير) في نفس
    الشاشة، للقراءة معًا. الإنشاء/الاعتماد/الترحيل/العكس متاحة فقط
    للقيود اليدوية (source_type فارغ) عبر الإجراءات أدناه."""

    serializer_class = JournalEntrySerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    permission_map = {
        "list": "accounting.view",
        "retrieve": "accounting.view",
        "create": "accounting.manage",
        "submit": "accounting.manage",
        "approve": "accounting.manage",
        "post": "accounting.manage",
        "reverse": "accounting.manage",
        "trial_balance": "accounting.view",
    }

    def get_queryset(self):
        accessible_ids = get_accessible_entity_ids(self.request.user)
        return (
            JournalEntry.objects.filter(
                tenant=self.request.user.tenant, legal_entity_id__in=accessible_ids
            )
            .prefetch_related("lines", "lines__account")
        )

    def _resolve_currency_and_rate(self, tenant, legal_entity, currency, exchange_rate, date):
        currency = currency or legal_entity.base_currency
        if currency == legal_entity.base_currency:
            return currency, Decimal("1")
        if exchange_rate is not None:
            return currency, exchange_rate
        return currency, get_rate(tenant, currency, legal_entity.base_currency, date)

    def create(self, request, *args, **kwargs):
        serializer = ManualJournalEntryCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        tenant = request.user.tenant
        try:
            currency, exchange_rate = self._resolve_currency_and_rate(
                tenant, data["legal_entity"], data.get("currency"), data.get("exchange_rate"), data["date"]
            )
            resolved_lines = _resolve_manual_lines(tenant, data["lines"])
            entry = create_manual_journal_entry(
                tenant=tenant,
                user=request.user,
                legal_entity=data["legal_entity"],
                date=data["date"],
                line_specs=resolved_lines,
                currency=currency,
                exchange_rate=exchange_rate,
                memo=data.get("memo", ""),
                reference=data.get("reference", ""),
            )
        except ExchangeRateNotFound as exc:
            return Response({"detail": str(exc.message)}, status=400)
        except (ValidationError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(JournalEntrySerializer(entry).data, status=201)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        return self._run_transition(submit_journal_entry_for_approval, request)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._run_transition(approve_journal_entry, request)

    @action(detail=True, methods=["post"])
    def post(self, request, pk=None):
        return self._run_transition(post_journal_entry, request)

    def _run_transition(self, fn, request):
        entry = self.get_object()
        try:
            fn(entry, request.user)
        except (ValidationError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=400)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=403)
        return Response(JournalEntrySerializer(entry).data)

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        entry = self.get_object()
        if entry.source_type:
            # A system-generated entry (currently only invoices) has
            # its own reversal path (Invoice.void() ->
            # void_invoice_journal_entry) that also updates the source
            # document's own status — reversing it here directly would
            # desync Invoice.status from its journal entry.
            return Response(
                {"detail": "This entry was generated automatically; reverse it from its source document instead."},
                status=400,
            )
        serializer = JournalEntryReverseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            reversal = reverse_journal_entry(entry, request.user, serializer.validated_data["reason"])
        except (ValidationError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(JournalEntrySerializer(reversal).data, status=201)

    @action(detail=False, methods=["get"])
    def trial_balance(self, request):
        tenant = request.user.tenant
        result = compute_trial_balance(
            tenant,
            legal_entity_id=request.query_params.get("legal_entity"),
            date_from=request.query_params.get("date_from"),
            date_to=request.query_params.get("date_to"),
        )
        return Response(
            {
                "rows": [
                    {**row, "debit": str(row["debit"]), "credit": str(row["credit"]), "balance": str(row["balance"])}
                    for row in result["rows"]
                ],
                "total_debit": str(result["total_debit"]),
                "total_credit": str(result["total_credit"]),
            }
        )
