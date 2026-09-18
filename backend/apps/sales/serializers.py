from decimal import Decimal

from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.accounting.services import post_invoice_journal_entry
from apps.organization.models import CostCenter, LegalEntity
from apps.organization.services import default_branch_for_tenant, get_accessible_entity_ids

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
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    legal_entity_name = serializers.CharField(source="legal_entity.name", read_only=True)

    class Meta:
        model = Invoice
        fields = (
            "id", "number", "status", "issue_date", "customer", "customer_name",
            "legal_entity", "legal_entity_name",
            "subtotal", "tax_total", "total", "lines", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "number", "status", "customer_name", "legal_entity_name", "subtotal",
            "tax_total", "total", "lines", "created_at", "updated_at",
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
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.none())
    # Mandatory (rule 3) but may be omitted by the client when the
    # tenant is in simplified mode (3.13) — auto-filled server-side with
    # the tenant's single branch in that case; see validate() below.
    legal_entity = serializers.PrimaryKeyRelatedField(
        queryset=LegalEntity.objects.none(), required=False
    )
    issue_date = serializers.DateField(required=False)
    lines = InvoiceLineInputSerializer(many=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            tenant = request.user.tenant
            self.fields["customer"].queryset = Customer.objects.filter(tenant=tenant)
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
        return attrs

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
        return create_invoice(
            tenant=tenant,
            customer=validated_data["customer"],
            legal_entity=validated_data["legal_entity"],
            issue_date=validated_data.get("issue_date") or timezone.localdate(),
            line_inputs=resolved_lines,
        )

    def update(self, instance, validated_data):
        tenant = self.context["request"].user.tenant
        resolved_lines = self._resolve_lines(tenant, validated_data["lines"])
        return update_invoice(
            instance,
            customer=validated_data["customer"],
            legal_entity=validated_data["legal_entity"],
            issue_date=validated_data.get("issue_date") or instance.issue_date,
            line_inputs=resolved_lines,
        )


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
