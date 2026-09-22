from decimal import Decimal

from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.accounting.services import post_invoice_journal_entry
from apps.common.constants import RATE_DECIMAL_PLACES, RATE_MAX_DIGITS
from apps.organization.models import CostCenter, LegalEntity
from apps.organization.services import default_branch_for_tenant, get_accessible_entity_ids
from apps.parties.models import Party, PartyRole
from apps.platform.models import AuditLog
from apps.platform.services import log_action
from apps.treasury.services import ExchangeRateNotFound, get_rate

from .models import Customer, Invoice, InvoiceLine, Product
from .services import create_invoice, update_invoice


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ("id", "name", "email", "phone", "tax_number", "address", "is_active", "created_at")
        read_only_fields = ("id", "created_at")


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ("id", "sku", "name", "unit_price", "tax_rate", "is_active", "created_at")
        read_only_fields = ("id", "created_at")


class InvoiceLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceLine
        fields = (
            "id", "product", "cost_center", "description", "quantity", "unit_price",
            "tax_rate", "line_subtotal", "line_tax", "line_total",
        )
        read_only_fields = fields


class InvoiceSerializer(serializers.ModelSerializer):
    lines = InvoiceLineSerializer(many=True, read_only=True)
    # Sprint 3 (3.3): the underlying model field is `party` (FK to
    # parties.Party, role=CUSTOMER) — the API keeps the "customer" name
    # for continuity with the existing invoice screens/tests, since
    # conceptually it's still "who this invoice is billed to".
    customer = serializers.PrimaryKeyRelatedField(source="party", read_only=True)
    customer_name = serializers.CharField(source="party.name", read_only=True)
    legal_entity_name = serializers.CharField(source="legal_entity.name", read_only=True)

    class Meta:
        model = Invoice
        fields = (
            "id", "number", "status", "issue_date", "customer", "customer_name",
            "legal_entity", "legal_entity_name", "currency", "exchange_rate",
            "subtotal", "tax_total", "total", "base_total", "lines", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "number", "status", "customer_name", "legal_entity_name", "currency",
            "exchange_rate", "subtotal", "tax_total", "total", "base_total", "lines",
            "created_at", "updated_at",
        )


class InvoiceLineInputSerializer(serializers.Serializer):
    # `product`/`cost_center` are bare UUIDs here, not
    # PrimaryKeyRelatedFields: that field type is declared once at
    # class-definition time (this serializer is nested as
    # `InvoiceCreateSerializer.lines`), long before any request context
    # exists, so a queryset scoped to request.user.tenant can't be bound
    # to it per-request. Tenant scoping is enforced explicitly in
    # InvoiceCreateSerializer.create() instead, which resolves each id
    # against the caller's tenant.
    product = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    # Optional, line-level (docs/SYSTEM_ANALYSIS.md 3.2/3.3) — never
    # required, never on the document.
    cost_center = serializers.UUIDField(required=False, allow_null=True)


class InvoiceCreateSerializer(serializers.Serializer):
    # Sprint 3 (3.3): "في الفاتورة: اختيار العميل من الأطراف بدور
    # CUSTOMER فقط" — the queryset below (set per-request in __init__)
    # only offers parties holding an active CUSTOMER role, so a party
    # without that role 400s exactly like any other invalid id, same as
    # picking another tenant's party.
    customer = serializers.PrimaryKeyRelatedField(source="party", queryset=Party.objects.none())
    # Mandatory (rule 3) but may be omitted by the client when the
    # tenant is in simplified mode (3.13) — auto-filled server-side with
    # the tenant's single branch in that case; see validate() below.
    legal_entity = serializers.PrimaryKeyRelatedField(
        queryset=LegalEntity.objects.none(), required=False
    )
    issue_date = serializers.DateField(required=False)
    # Sprint 4.2 (3.11/3.15.3): both optional. currency defaults to the
    # invoice's legal_entity's base currency (the common, single-
    # currency case for most small clients never needs either field);
    # exchange_rate, if omitted, is auto-pulled from ExchangeRate by
    # issue_date — see validate() below, which is where both actually
    # get resolved (legal_entity/issue_date must already be resolved
    # first).
    currency = serializers.CharField(max_length=3, required=False)
    exchange_rate = serializers.DecimalField(
        max_digits=RATE_MAX_DIGITS, decimal_places=RATE_DECIMAL_PLACES, required=False
    )
    lines = InvoiceLineInputSerializer(many=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            tenant = request.user.tenant
            self.fields["customer"].queryset = Party.objects.filter(
                tenant=tenant, roles__role=PartyRole.Role.CUSTOMER, roles__is_active=True
            )
            accessible_ids = get_accessible_entity_ids(request.user)
            self.fields["legal_entity"].queryset = LegalEntity.objects.filter(
                tenant=tenant, id__in=accessible_ids
            )

    def validate_lines(self, value):
        if not value:
            raise serializers.ValidationError(_("At least one invoice line is required."))
        return value

    def validate(self, attrs):
        if "legal_entity" not in attrs:
            tenant = self.context["request"].user.tenant
            default_branch = default_branch_for_tenant(tenant)
            if default_branch is None:
                raise serializers.ValidationError(
                    {"legal_entity": [_("This field is required.")]}
                )
            attrs["legal_entity"] = default_branch

        legal_entity = attrs["legal_entity"]
        currency = attrs.get("currency") or legal_entity.base_currency
        attrs["currency"] = currency
        issue_date = attrs.get("issue_date") or timezone.localdate()

        if currency == legal_entity.base_currency:
            # Same currency is always rate 1 — an explicit override
            # here would be meaningless, so it's ignored rather than
            # honored (never silently wrong money, just a no-op field).
            attrs["exchange_rate"] = Decimal("1")
            attrs["_rate_overridden"] = False
        elif "exchange_rate" in attrs:
            attrs["_rate_overridden"] = True
        else:
            tenant = self.context["request"].user.tenant
            try:
                attrs["exchange_rate"] = get_rate(tenant, currency, legal_entity.base_currency, issue_date)
            except ExchangeRateNotFound as exc:
                raise serializers.ValidationError({"exchange_rate": [str(exc.message)]})
            attrs["_rate_overridden"] = False

        return attrs

    def _log_rate_override_if_needed(self, invoice, attrs):
        if not attrs.pop("_rate_overridden", False):
            return
        request = self.context["request"]
        log_action(
            actor_type=AuditLog.ActorType.TENANT_USER,
            actor_id=request.user.id,
            action="invoice.exchange_rate_overridden",
            target_type="invoice",
            target_id=invoice.id,
            tenant_id=request.user.tenant_id,
            after={"currency": invoice.currency, "exchange_rate": str(invoice.exchange_rate)},
            request=request,
        )

    def _resolve_lines(self, tenant, raw_lines):
        resolved = []
        for line in raw_lines:
            try:
                product = Product.objects.get(
                    tenant=tenant, id=line["product"], is_active=True
                )
            except Product.DoesNotExist:
                raise serializers.ValidationError(
                    {"lines": [_("Product not found.")]}
                )
            cost_center = None
            cost_center_id = line.get("cost_center")
            if cost_center_id:
                try:
                    cost_center = CostCenter.objects.get(tenant=tenant, id=cost_center_id)
                except CostCenter.DoesNotExist:
                    raise serializers.ValidationError(
                        {"lines": [_("Cost center not found.")]}
                    )
            resolved.append(
                {"product": product, "quantity": line["quantity"], "cost_center": cost_center}
            )
        return resolved

    def create(self, validated_data):
        request = self.context["request"]
        tenant = request.user.tenant
        resolved_lines = self._resolve_lines(tenant, validated_data["lines"])
        invoice = create_invoice(
            tenant=tenant,
            party=validated_data["party"],
            legal_entity=validated_data["legal_entity"],
            issue_date=validated_data.get("issue_date") or timezone.localdate(),
            line_inputs=resolved_lines,
            currency=validated_data["currency"],
            exchange_rate=validated_data["exchange_rate"],
        )
        self._log_rate_override_if_needed(invoice, validated_data)
        return invoice

    def update(self, instance, validated_data):
        tenant = self.context["request"].user.tenant
        resolved_lines = self._resolve_lines(tenant, validated_data["lines"])
        invoice = update_invoice(
            instance,
            party=validated_data["party"],
            legal_entity=validated_data["legal_entity"],
            issue_date=validated_data.get("issue_date") or instance.issue_date,
            line_inputs=resolved_lines,
            currency=validated_data["currency"],
            exchange_rate=validated_data["exchange_rate"],
        )
        self._log_rate_override_if_needed(invoice, validated_data)
        return invoice


class InvoiceIssueSerializer(serializers.Serializer):
    """No input fields — issuing an invoice only transitions its status
    and posts the journal entry; nothing about it is client-supplied."""

    def save(self, invoice):
        if invoice.status != Invoice.Status.DRAFT:
            raise serializers.ValidationError(_("Only draft invoices can be issued."))
        invoice.status = Invoice.Status.ISSUED
        invoice.save(update_fields=["status"])
        post_invoice_journal_entry(invoice)
        return invoice
