from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models
from rest_framework import serializers

from apps.common.serializers import validate_iban_field
from apps.common.validators import validate_iban
from apps.organization.models import LegalEntity
from apps.parties.models import Party, PartyRole

from .models import (
    Bank,
    BankStatement,
    BankStatementLine,
    CashBox,
    CashCount,
    Custody,
    ExchangeRate,
    IbanChangeRequest,
)


def _employee_party_queryset(tenant):
    return Party.objects.filter(
        tenant=tenant, roles__role=PartyRole.Role.EMPLOYEE, roles__is_active=True
    )


class _TenantScopedRelationsMixin:
    """Scopes `legal_entity` (every model here) and any employee/party
    relation field named in `party_fields` to the caller's own tenant —
    same pattern as InvoiceCreateSerializer.customer."""

    party_fields: tuple[str, ...] = ()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            tenant = request.user.tenant
            if "legal_entity" in self.fields:
                self.fields["legal_entity"].queryset = LegalEntity.objects.filter(tenant=tenant)
            for field_name in self.party_fields:
                self.fields[field_name].queryset = _employee_party_queryset(tenant)


def _has_voucher_movements(tenant_id, field_name, obj_id):
    """Sprint 6.5.15 (UAT item 5): whether any Voucher (either side of
    a transfer) has ever posted against this treasury account — the
    same "does it have real history" check the entity-move migration
    itself uses, exposed here so the frontend can make `legal_entity`
    read-only instead of letting an edit silently detach a real
    movement's own posting entity from what the account now claims."""
    from apps.vouchers.models import Voucher

    return Voucher.objects.filter(tenant_id=tenant_id).filter(
        models.Q(**{field_name: obj_id}) | models.Q(**{f"counter_{field_name}": obj_id})
    ).exists()


class BankSerializer(_TenantScopedRelationsMixin, serializers.ModelSerializer):
    has_movements = serializers.SerializerMethodField()

    class Meta:
        model = Bank
        fields = (
            "id", "legal_entity", "name", "bank_name", "account_number", "iban", "swift",
            "currency", "is_active", "has_movements", "created_at",
        )
        read_only_fields = ("id", "has_movements", "created_at")

    def get_has_movements(self, obj):
        return _has_voucher_movements(obj.tenant_id, "bank", obj.id)

    def validate_iban(self, value):
        # Sprint 5.5 (block 5.5.0, CFO_REVIEW_1 C10): first entry free,
        # any change to an already-set value must go through
        # treasury.IbanChangeRequest — same rule as Party.iban.
        current = self.instance.iban if self.instance else ""
        return validate_iban_field(value, current)


class CashBoxSerializer(_TenantScopedRelationsMixin, serializers.ModelSerializer):
    party_fields = ("custodian",)
    has_movements = serializers.SerializerMethodField()

    class Meta:
        model = CashBox
        fields = (
            "id", "legal_entity", "name", "currency", "custodian", "max_balance", "is_active",
            "has_movements", "created_at",
        )
        read_only_fields = ("id", "has_movements", "created_at")

    def get_has_movements(self, obj):
        return _has_voucher_movements(obj.tenant_id, "cash_box", obj.id)


class CustodySerializer(_TenantScopedRelationsMixin, serializers.ModelSerializer):
    party_fields = ("employee",)
    has_movements = serializers.SerializerMethodField()

    class Meta:
        model = Custody
        fields = (
            "id", "legal_entity", "employee", "name", "currency", "limit_amount", "is_active",
            "has_movements", "created_at",
        )
        read_only_fields = ("id", "has_movements", "created_at")

    def get_has_movements(self, obj):
        return _has_voucher_movements(obj.tenant_id, "custody", obj.id)


class ExchangeRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExchangeRate
        fields = (
            "id", "from_currency", "to_currency", "date", "rate", "source", "created_by", "created_at",
        )
        read_only_fields = ("id", "created_by", "created_at")

    def validate(self, attrs):
        if attrs.get("from_currency") == attrs.get("to_currency"):
            raise serializers.ValidationError(
                {"to_currency": ["From/to currency must be different — same-currency rate is always 1."]}
            )
        return attrs


class IbanChangeRequestCreateSerializer(serializers.Serializer):
    """Sprint 5.5 (block 5.5.0, CFO_REVIEW_1 C10). Plain input
    serializer (not a ModelSerializer) — the row itself is built by
    apps.treasury.services.create_iban_change_request, same split as
    VoucherCreateSerializer/create_voucher."""

    target_type = serializers.ChoiceField(choices=["bank", "party"])
    target_id = serializers.UUIDField()
    new_iban = serializers.CharField(max_length=34)
    reason = serializers.CharField()

    def validate_new_iban(self, value):
        # The approved value is applied straight to Bank.iban/Party.iban
        # by services._apply_iban_change, bypassing those serializers'
        # own validate_iban entirely — so the same format/checksum check
        # has to happen here instead, not skipped.
        try:
            validate_iban(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message)
        return value


class IbanChangeRequestSerializer(serializers.ModelSerializer):
    target_type = serializers.SerializerMethodField()
    target_id = serializers.UUIDField(source="object_id", read_only=True)
    target_label = serializers.SerializerMethodField()

    class Meta:
        model = IbanChangeRequest
        fields = (
            "id", "target_type", "target_id", "target_label", "old_iban", "new_iban", "reason",
            "status", "created_by", "decided_by", "decided_at", "created_at",
        )
        read_only_fields = fields

    def get_target_type(self, obj):
        return obj.content_type.model_class()._meta.model_name

    def get_target_label(self, obj):
        target = obj.target
        return str(target) if target is not None else None


class StatementImportSerializer(serializers.Serializer):
    """Sprint 5.5 (block 5.5.1). Plain input serializer — the row and
    its lines are built by apps.treasury.services.import_bank_statement,
    same split as every other create-flow in this project."""

    file = serializers.FileField()
    format = serializers.ChoiceField(choices=["csv", "xlsx", "mt940"], source="import_format")
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    opening_balance = serializers.DecimalField(max_digits=18, decimal_places=2)
    closing_balance = serializers.DecimalField(max_digits=18, decimal_places=2)
    currency = serializers.CharField(max_length=3, required=False, allow_blank=True)
    column_mapping = serializers.JSONField(required=False)


class BankStatementLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankStatementLine
        fields = (
            "id", "line_no", "date", "amount", "description", "reference", "status",
            "matched_by", "matched_by_user", "matched_at", "ignored_reason",
        )
        read_only_fields = fields


class _ReconciledRatioMixin:
    def get_reconciled_ratio(self, obj):
        total = obj.line_count
        if not total:
            return 0.0
        settled = obj.lines.exclude(status=BankStatementLine.Status.UNMATCHED).count()
        return round(settled / total, 4)


class BankStatementListSerializer(_ReconciledRatioMixin, serializers.ModelSerializer):
    """`GET /api/banks/{id}/statements/` — period, line count, and
    reconciliation ratio only (no lines — avoids an N+1 per row)."""

    reconciled_ratio = serializers.SerializerMethodField()

    class Meta:
        model = BankStatement
        fields = (
            "id", "bank", "period_start", "period_end", "currency", "opening_balance", "closing_balance",
            "import_format", "line_count", "imported_by", "reconciled_ratio", "created_at",
        )
        read_only_fields = fields


class BankStatementSerializer(_ReconciledRatioMixin, serializers.ModelSerializer):
    """`GET /api/banks/{id}/statements/{id}/` and the import response —
    full lines included."""

    reconciled_ratio = serializers.SerializerMethodField()
    lines = BankStatementLineSerializer(many=True, read_only=True)

    class Meta:
        model = BankStatement
        fields = (
            "id", "bank", "period_start", "period_end", "currency", "opening_balance", "closing_balance",
            "import_format", "line_count", "imported_by", "reconciled_ratio", "lines", "created_at",
        )
        read_only_fields = fields


class MatchStatementLineSerializer(serializers.Serializer):
    journal_line_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1)


class IgnoreStatementLineSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=3)


class CashCountCreateSerializer(serializers.Serializer):
    """Sprint 5.5 (block 5.5.3, CFO_REVIEW_1 F14). Plain input
    serializer — the row is built by
    apps.treasury.services.create_cash_count, same split as every
    other create-flow in this project."""

    cash_box = serializers.PrimaryKeyRelatedField(queryset=CashBox.objects.none())
    count_date = serializers.DateField()
    counted_amount = serializers.DecimalField(max_digits=18, decimal_places=2, required=False)
    denominations = serializers.JSONField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            self.fields["cash_box"].queryset = CashBox.objects.filter(tenant=request.user.tenant)


class CashCountConfirmSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    create_variance_voucher = serializers.BooleanField(required=False, default=False)


class CashCountSerializer(serializers.ModelSerializer):
    class Meta:
        model = CashCount
        fields = (
            "id", "cash_box", "number", "count_date", "counted_by", "denominations", "counted_amount",
            "book_balance_snapshot", "difference", "reason", "status", "confirmed_by", "confirmed_at",
            "variance_voucher", "created_at",
        )
        read_only_fields = fields
