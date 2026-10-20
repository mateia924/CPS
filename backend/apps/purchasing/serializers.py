from decimal import Decimal

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.organization.models import LegalEntity
from apps.parties.models import Party

from .models import PurchaseSettings, WithholdingTaxCode


class PurchaseSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseSettings
        fields = ("match_tolerance_pct", "match_tolerance_amount", "default_grni_policy")

    def validate_match_tolerance_pct(self, value):
        if not Decimal("0") <= value <= Decimal("100"):
            raise serializers.ValidationError(_("The tolerance percentage must be between 0 and 100."))
        return value

    def validate_match_tolerance_amount(self, value):
        if value < 0:
            raise serializers.ValidationError(_("The tolerance amount cannot be negative."))
        return value


class WithholdingTaxCodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = WithholdingTaxCode
        fields = ("id", "country", "code", "name_ar", "rate", "base", "applies_to", "is_example", "is_active")
        read_only_fields = fields


# -- Sprint 8.1: supplier bills ---------------------------------------------------


class SupplierBillLineSerializer(serializers.ModelSerializer):
    line_type_label = serializers.CharField(source="get_line_type_display", read_only=True)
    account_code = serializers.CharField(source="account.code", read_only=True, default=None)
    account_name = serializers.CharField(source="account.name", read_only=True, default=None)
    cost_center_name = serializers.CharField(source="cost_center.name", read_only=True, default=None)
    tax_code_display = serializers.CharField(source="tax_code.code", read_only=True)
    tax_rate = serializers.DecimalField(source="tax_code.rate", max_digits=5, decimal_places=2, read_only=True)
    is_reverse_charge = serializers.SerializerMethodField()
    wht_code_display = serializers.CharField(source="wht_code.code", read_only=True, default=None)
    asset_code = serializers.CharField(source="asset.code", read_only=True, default=None)

    class Meta:
        from .models import SupplierBillLine

        model = SupplierBillLine
        fields = (
            "id", "line_no", "line_type", "line_type_label", "description", "account", "account_code", "account_name",
            "cost_center", "cost_center_name", "qty", "unit_price", "tax_code", "tax_code_display", "tax_rate",
            "is_reverse_charge", "vat_deductible", "wht_code", "wht_code_display", "asset_name", "asset_category",
            "asset", "asset_code", "net", "tax_amount", "capitalized_tax", "cost", "payable", "wht_base", "wht_amount",
        )
        read_only_fields = fields

    def get_is_reverse_charge(self, obj):
        return obj.tax_code.kind == "reverse_charge"


class SupplierBillSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    legal_entity_name = serializers.CharField(source="legal_entity.name", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    journal_entry_number = serializers.CharField(source="journal_entry.number", read_only=True, default=None)
    created_by_id = serializers.UUIDField(read_only=True)
    lines = SupplierBillLineSerializer(many=True, read_only=True)

    class Meta:
        from .models import SupplierBill

        model = SupplierBill
        fields = (
            "id", "number", "status", "status_label", "legal_entity", "legal_entity_name", "supplier", "supplier_name",
            "bill_number", "date", "due_date", "currency", "exchange_rate", "reference", "notes", "subtotal",
            "deductible_tax", "capitalized_tax", "reverse_charge_tax", "wht_expected", "total", "base_total",
            "journal_entry", "journal_entry_number", "created_by_id", "created_at", "posted_at", "lines",
        )
        read_only_fields = fields


class SupplierBillLineInputSerializer(serializers.Serializer):
    line_type = serializers.CharField()
    description = serializers.CharField(required=False, allow_blank=True, default="")
    account = serializers.UUIDField(required=False, allow_null=True)
    cost_center = serializers.UUIDField(required=False, allow_null=True)
    qty = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, default=Decimal("1"))
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    tax_code = serializers.UUIDField()
    vat_deductible = serializers.BooleanField(required=False, default=True)
    wht_code = serializers.UUIDField(required=False, allow_null=True)
    asset_name = serializers.CharField(required=False, allow_blank=True, default="")
    asset_category = serializers.CharField(required=False, allow_blank=True, default="")


class SupplierBillInputSerializer(serializers.Serializer):
    """Header + lines in; the money is all computed server-side
    (apps.purchasing.bills). Currency/rate and the open-period check follow
    InvoiceCreateSerializer exactly."""

    legal_entity = serializers.PrimaryKeyRelatedField(queryset=LegalEntity.objects.none())
    supplier = serializers.PrimaryKeyRelatedField(queryset=Party.objects.none())
    bill_number = serializers.CharField(max_length=64, allow_blank=True)
    date = serializers.DateField(required=False)
    due_date = serializers.DateField(required=False, allow_null=True)
    currency = serializers.CharField(max_length=3, required=False)
    exchange_rate = serializers.DecimalField(max_digits=18, decimal_places=8, required=False)
    reference = serializers.CharField(max_length=100, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    lines = SupplierBillLineInputSerializer(many=True, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.organization.services import get_accessible_entity_ids

        user = self.context["request"].user
        self.fields["legal_entity"].queryset = LegalEntity.objects.filter(
            tenant=user.tenant, id__in=get_accessible_entity_ids(user)
        )
        self.fields["supplier"].queryset = Party.objects.filter(tenant=user.tenant)

    def validate(self, attrs):
        from django.core.exceptions import ValidationError as DjangoValidationError
        from django.utils import timezone

        from apps.accounting.periods import assert_open_period
        from apps.treasury.services import ExchangeRateNotFound, get_rate_with_warnings

        tenant = self.context["request"].user.tenant
        self.rate_warnings = []
        if self.partial and "legal_entity" not in attrs:
            return attrs
        legal_entity = attrs["legal_entity"]
        attrs["currency"] = currency = (attrs.get("currency") or legal_entity.base_currency).upper()
        attrs["date"] = bill_date = attrs.get("date") or timezone.localdate()
        try:
            assert_open_period(tenant, bill_date)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"date": [" ".join(exc.messages)]})
        if currency == legal_entity.base_currency:
            attrs["exchange_rate"] = Decimal("1")
        elif "exchange_rate" not in attrs:
            try:
                attrs["exchange_rate"], self.rate_warnings = get_rate_with_warnings(
                    tenant, currency, legal_entity.base_currency, bill_date
                )
            except ExchangeRateNotFound as exc:
                raise serializers.ValidationError({"exchange_rate": [str(exc.message)]})
        return attrs
