from decimal import Decimal

from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.accounting.services import post_invoice_journal_entry

from .models import Customer, Invoice, InvoiceLine, Product
from .services import create_invoice


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ("id", "name", "email", "phone", "tax_number", "address", "created_at")
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
            "id", "product", "description", "quantity", "unit_price",
            "tax_rate", "line_subtotal", "line_tax", "line_total",
        )
        read_only_fields = fields


class InvoiceSerializer(serializers.ModelSerializer):
    lines = InvoiceLineSerializer(many=True, read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True)

    class Meta:
        model = Invoice
        fields = (
            "id", "number", "status", "issue_date", "customer", "customer_name",
            "subtotal", "tax_total", "total", "lines", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "number", "status", "customer_name", "subtotal", "tax_total",
            "total", "lines", "created_at", "updated_at",
        )


class InvoiceLineInputSerializer(serializers.Serializer):
    # `product` is a bare UUID here, not a PrimaryKeyRelatedField: that
    # field type is declared once at class-definition time (this
    # serializer is nested as `InvoiceCreateSerializer.lines`), long
    # before any request context exists, so a queryset scoped to
    # request.user.tenant can't be bound to it per-request. Tenant
    # scoping is enforced explicitly in InvoiceCreateSerializer.create()
    # instead, which resolves each product against the caller's tenant.
    product = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))


class InvoiceCreateSerializer(serializers.Serializer):
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.none())
    issue_date = serializers.DateField(required=False)
    lines = InvoiceLineInputSerializer(many=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            self.fields["customer"].queryset = Customer.objects.filter(tenant=request.user.tenant)

    def validate_lines(self, value):
        if not value:
            raise serializers.ValidationError(_("At least one invoice line is required."))
        return value

    def create(self, validated_data):
        request = self.context["request"]
        tenant = request.user.tenant

        resolved_lines = []
        for line in validated_data["lines"]:
            try:
                product = Product.objects.get(
                    tenant=tenant, id=line["product"], is_active=True
                )
            except Product.DoesNotExist:
                raise serializers.ValidationError(
                    {"lines": [_("Product not found.")]}
                )
            resolved_lines.append({"product": product, "quantity": line["quantity"]})

        invoice = create_invoice(
            tenant=tenant,
            customer=validated_data["customer"],
            issue_date=validated_data.get("issue_date") or timezone.localdate(),
            line_inputs=resolved_lines,
        )
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
