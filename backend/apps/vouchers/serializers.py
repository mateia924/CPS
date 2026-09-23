from decimal import Decimal

from rest_framework import serializers

from apps.accounting.models import Account, TaxCode
from apps.organization.models import CostCenter, LegalEntity
from apps.organization.services import get_accessible_entity_ids
from apps.parties.models import Party
from apps.sales.models import Invoice
from apps.treasury.models import Bank, BankStatementLine, CashBox, Custody

from .models import Voucher, VoucherLine


class VoucherLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = VoucherLine
        fields = (
            "id", "line_no", "line_type", "invoice", "allocated_invoice_fc",
            "account", "tax_code", "amount_includes_tax", "tax_amount_fc",
            "ext_supplier_name", "ext_supplier_tax_number", "ext_invoice_ref",
            "cost_center", "description", "amount_fc", "amount_base", "tax_amount_base",
        )
        read_only_fields = fields


class VoucherSerializer(serializers.ModelSerializer):
    lines = VoucherLineSerializer(many=True, read_only=True)
    legal_entity_name = serializers.CharField(source="legal_entity.name", read_only=True)
    party_name = serializers.CharField(source="party.name", read_only=True)
    treasury_name = serializers.SerializerMethodField()
    counter_treasury_name = serializers.SerializerMethodField()
    journal_entry_id = serializers.PrimaryKeyRelatedField(source="journal_entry", read_only=True)

    class Meta:
        model = Voucher
        fields = (
            "id", "voucher_type", "settlement_kind", "number", "date",
            "currency", "exchange_rate", "exchange_rate_overridden",
            "treasury_kind", "bank", "cash_box", "custody", "treasury_name",
            "counter_treasury_kind", "counter_bank", "counter_cash_box", "counter_custody", "counter_amount_fc",
            "counter_treasury_name",
            "legal_entity", "legal_entity_name", "party", "party_name", "party_role", "payee_name",
            "payment_method", "reference", "description", "status",
            "total_fc", "total_base", "journal_entry_id", "created_by", "posted_at", "reversal_of",
            "lines", "created_at",
        )
        read_only_fields = fields

    def get_treasury_name(self, obj):
        instance = getattr(obj, obj.treasury_kind, None)
        return instance.name if instance else ""

    def get_counter_treasury_name(self, obj):
        if not obj.counter_treasury_kind:
            return ""
        instance = getattr(obj, f"counter_{obj.counter_treasury_kind}", None)
        return instance.name if instance else ""


# ---------------------------------------------------------------------
# Create input — a raw Serializer (not ModelSerializer): lines are
# heterogeneous by line_type and every id must resolve within the
# caller's own tenant, same split as ManualJournalEntryCreateSerializer
# (4.4) and InvoiceCreateSerializer (3/4.2).
# ---------------------------------------------------------------------


class VoucherLineInputSerializer(serializers.Serializer):
    line_type = serializers.ChoiceField(choices=VoucherLine.LineType.choices)
    invoice = serializers.UUIDField(required=False)
    allocated_invoice_fc = serializers.DecimalField(max_digits=14, decimal_places=2, required=False)
    account = serializers.UUIDField(required=False)
    tax_code = serializers.UUIDField(required=False, allow_null=True)
    amount_includes_tax = serializers.BooleanField(required=False, default=False)
    ext_supplier_name = serializers.CharField(required=False, allow_blank=True, default="")
    ext_supplier_tax_number = serializers.CharField(required=False, allow_blank=True, default="")
    ext_invoice_ref = serializers.CharField(required=False, allow_blank=True, default="")
    cost_center = serializers.UUIDField(required=False, allow_null=True)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    amount_fc = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))

    def validate(self, attrs):
        line_type = attrs["line_type"]
        if line_type == VoucherLine.LineType.INVOICE and "invoice" not in attrs:
            raise serializers.ValidationError({"invoice": ["Required for an invoice-settlement line."]})
        if line_type == VoucherLine.LineType.ACCOUNT and "account" not in attrs:
            raise serializers.ValidationError({"account": ["Required for a direct-account line."]})
        return attrs


class VoucherCreateSerializer(serializers.Serializer):
    voucher_type = serializers.ChoiceField(choices=Voucher.VoucherType.choices)
    settlement_kind = serializers.ChoiceField(choices=Voucher.SettlementKind.choices, required=False, allow_null=True)
    legal_entity = serializers.PrimaryKeyRelatedField(queryset=LegalEntity.objects.none())
    date = serializers.DateField()
    treasury_kind = serializers.ChoiceField(choices=Voucher.TreasuryKind.choices)
    treasury_id = serializers.UUIDField()
    exchange_rate = serializers.DecimalField(max_digits=18, decimal_places=8, required=False)
    party = serializers.PrimaryKeyRelatedField(queryset=Party.objects.none(), required=False, allow_null=True)
    party_role = serializers.ChoiceField(choices=Voucher.PartyRoleChoice.choices, required=False, allow_blank=True, default="")
    payee_name = serializers.CharField(required=False, allow_blank=True, default="")
    payment_method = serializers.ChoiceField(choices=Voucher.PaymentMethod.choices, required=False, default=Voucher.PaymentMethod.CASH)
    reference = serializers.CharField(required=False, allow_blank=True, default="")
    description = serializers.CharField(required=False, allow_blank=True, default="")
    # Sprint 5.5 (block 5.5.2): "سند من هذا البند" — set only when the
    # voucher form was opened from a bank statement line's own button.
    statement_line = serializers.PrimaryKeyRelatedField(
        queryset=BankStatementLine.objects.none(), required=False, allow_null=True
    )
    lines = VoucherLineInputSerializer(many=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            tenant = request.user.tenant
            accessible_ids = get_accessible_entity_ids(request.user)
            self.fields["legal_entity"].queryset = LegalEntity.objects.filter(tenant=tenant, id__in=accessible_ids)
            self.fields["party"].queryset = Party.objects.filter(tenant=tenant)
            self.fields["statement_line"].queryset = BankStatementLine.objects.filter(tenant=tenant)

    def validate_lines(self, value):
        if not value:
            raise serializers.ValidationError("At least one line is required.")
        return value


def resolve_treasury_id_for_kind(tenant, kind, raw_id):
    model = {"bank": Bank, "cash_box": CashBox, "custody": Custody}[kind]
    return model.objects.filter(tenant=tenant, id=raw_id).values_list("id", flat=True).first()


def resolve_voucher_lines(tenant, raw_lines):
    """Raw-id line dicts (from VoucherLineInputSerializer.validated_data)
    -> resolved-object dicts (services.create_voucher's expected shape).
    Every id is looked up within `tenant` — a cross-tenant id 404s at
    the view, exactly like every other create-flow in this project."""
    resolved = []
    for raw in raw_lines:
        item = {"line_type": raw["line_type"], "amount_fc": raw["amount_fc"], "description": raw.get("description", "")}
        if raw["line_type"] == VoucherLine.LineType.INVOICE:
            try:
                item["invoice"] = Invoice.objects.get(tenant=tenant, id=raw["invoice"])
            except Invoice.DoesNotExist:
                raise serializers.ValidationError({"lines": ["Invoice not found."]})
            item["allocated_invoice_fc"] = raw.get("allocated_invoice_fc") or raw["amount_fc"]
        elif raw["line_type"] == VoucherLine.LineType.ACCOUNT:
            try:
                item["account"] = Account.objects.get(tenant=tenant, id=raw["account"])
            except Account.DoesNotExist:
                raise serializers.ValidationError({"lines": ["Account not found."]})
            if raw.get("tax_code"):
                try:
                    item["tax_code"] = TaxCode.objects.get(tenant=tenant, id=raw["tax_code"])
                except TaxCode.DoesNotExist:
                    raise serializers.ValidationError({"lines": ["Tax code not found."]})
            item["amount_includes_tax"] = raw.get("amount_includes_tax", False)
        if raw.get("cost_center"):
            try:
                item["cost_center"] = CostCenter.objects.get(tenant=tenant, id=raw["cost_center"])
            except CostCenter.DoesNotExist:
                raise serializers.ValidationError({"lines": ["Cost center not found."]})
        resolved.append(item)
    return resolved


class RejectVoucherSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=3)


class InternalTransferCreateSerializer(serializers.Serializer):
    """Sprint 5.4 (block 5.4) — a separate, lines-free input shape:
    an internal transfer isn't invoice/on_account/account lines, just
    a source and a destination treasury account."""

    legal_entity = serializers.PrimaryKeyRelatedField(queryset=LegalEntity.objects.none())
    date = serializers.DateField()
    treasury_kind = serializers.ChoiceField(choices=Voucher.TreasuryKind.choices)
    treasury_id = serializers.UUIDField()
    counter_treasury_kind = serializers.ChoiceField(choices=Voucher.TreasuryKind.choices)
    counter_treasury_id = serializers.UUIDField()
    amount_fc = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))
    counter_amount_fc = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, allow_null=True)
    reference = serializers.CharField(required=False, allow_blank=True, default="")
    description = serializers.CharField(required=False, allow_blank=True, default="")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            tenant = request.user.tenant
            accessible_ids = get_accessible_entity_ids(request.user)
            self.fields["legal_entity"].queryset = LegalEntity.objects.filter(tenant=tenant, id__in=accessible_ids)
