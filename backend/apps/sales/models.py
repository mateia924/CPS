import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.constants import (
    MONEY_DECIMAL_PLACES,
    MONEY_MAX_DIGITS,
    PERCENTAGE_DECIMAL_PLACES,
    PERCENTAGE_MAX_DIGITS,
    PRICE_DECIMAL_PLACES,
    PRICE_MAX_DIGITS,
    QUANTITY_DECIMAL_PLACES,
    QUANTITY_MAX_DIGITS,
    RATE_DECIMAL_PLACES,
    RATE_MAX_DIGITS,
)
from apps.common.models import TenantScopedModel


class Customer(TenantScopedModel):
    name = models.CharField(_("name"), max_length=255)
    email = models.EmailField(_("email"), blank=True)
    phone = models.CharField(_("phone"), max_length=50, blank=True)
    tax_number = models.CharField(_("tax number"), max_length=50, blank=True)
    address = models.TextField(_("address"), blank=True)
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Product(TenantScopedModel):
    sku = models.CharField(_("SKU"), max_length=64)
    name = models.CharField(_("name"), max_length=255)
    unit_price = models.DecimalField(
        _("unit price"), max_digits=PRICE_MAX_DIGITS, decimal_places=PRICE_DECIMAL_PLACES
    )
    tax_rate = models.DecimalField(
        _("tax rate (%)"),
        max_digits=PERCENTAGE_MAX_DIGITS,
        decimal_places=PERCENTAGE_DECIMAL_PLACES,
        default=0,
    )
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "sku"], name="unique_product_sku_per_tenant")
        ]

    def __str__(self):
        return self.name


class Invoice(TenantScopedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        ISSUED = "issued", _("Issued")
        PAID = "paid", _("Paid")
        CANCELLED = "cancelled", _("Cancelled")

    # Sprint 3 (3.3): superseded by `party` below (FK to parties.Party,
    # role=CUSTOMER) — kept, untouched, purely for historical reference;
    # no code reads or writes this field going forward. See the Decision
    # Log for why the column is kept rather than dropped.
    legacy_customer = models.ForeignKey(
        Customer, null=True, blank=True, on_delete=models.PROTECT, related_name="invoices"
    )
    party = models.ForeignKey("parties.Party", on_delete=models.PROTECT, related_name="invoices")
    # Mandatory per docs/SYSTEM_ANALYSIS.md section 4 rule 3. Went
    # through the 3-step safe migration for pre-sprint-1 rows: nullable,
    # backfill, then NOT NULL (apps/sales/migrations/0002-0004).
    legal_entity = models.ForeignKey(
        "organization.LegalEntity", on_delete=models.PROTECT, related_name="invoices"
    )
    number = models.CharField(_("number"), max_length=32)
    status = models.CharField(_("status"), max_length=20, choices=Status.choices, default=Status.DRAFT)
    issue_date = models.DateField(_("issue date"))

    # Sprint 4.2 (3.11/3.15.3): defaults keep every pre-4.2 invoice
    # unchanged (currency=base, rate=1, base_total=total) — see the
    # migration backfill. `currency` is the invoice's own currency (line
    # amounts below are in this currency); `exchange_rate` converts 1
    # unit of it into legal_entity.base_currency.
    currency = models.CharField(_("currency"), max_length=3, default="SAR")
    exchange_rate = models.DecimalField(
        _("exchange rate"), max_digits=RATE_MAX_DIGITS, decimal_places=RATE_DECIMAL_PLACES, default=1
    )

    # Always computed server-side from the lines — never accepted as API input.
    subtotal = models.DecimalField(
        _("subtotal"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, default=0
    )
    tax_total = models.DecimalField(
        _("tax total"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, default=0
    )
    total = models.DecimalField(
        _("total"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, default=0
    )
    # total * exchange_rate, in legal_entity.base_currency — for reports
    # that must aggregate across invoices in different currencies
    # (docs/SYSTEM_ANALYSIS.md 3.15.3's spec: "base_total محسوب على
    # الفاتورة للتقارير").
    base_total = models.DecimalField(
        _("base total"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, default=0
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-issue_date", "-created_at"]
        constraints = [
            # Sprint 4.1: numbers are now generated per (tenant,
            # legal_entity, year) — apps.numbering.services.
            # next_document_number — not per tenant alone, so two
            # branches legitimately both issue "INV-2026-00001" as
            # their first invoice. The constraint must match that scope.
            models.UniqueConstraint(
                fields=["tenant", "legal_entity", "number"],
                name="unique_invoice_number_per_tenant_and_entity",
            )
        ]

    def __str__(self):
        return self.number


class InvoiceLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="invoice_lines")
    # Optional, line-level (3.2/3.3 in section 2 of the sprint spec) —
    # never on the document, only the line.
    cost_center = models.ForeignKey(
        "organization.CostCenter",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="invoice_lines",
    )

    # Snapshots taken from the product at invoicing time so historical
    # invoices don't change if the product is edited later.
    description = models.CharField(_("description"), max_length=255)
    quantity = models.DecimalField(
        _("quantity"), max_digits=QUANTITY_MAX_DIGITS, decimal_places=QUANTITY_DECIMAL_PLACES
    )
    unit_price = models.DecimalField(
        _("unit price"), max_digits=PRICE_MAX_DIGITS, decimal_places=PRICE_DECIMAL_PLACES
    )
    tax_rate = models.DecimalField(
        _("tax rate (%)"), max_digits=PERCENTAGE_MAX_DIGITS, decimal_places=PERCENTAGE_DECIMAL_PLACES
    )

    # Computed server-side by services.recalculate_invoice().
    line_subtotal = models.DecimalField(
        max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, default=0
    )
    line_tax = models.DecimalField(
        max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, default=0
    )
    line_total = models.DecimalField(
        max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, default=0
    )

    def __str__(self):
        return f"{self.description} x{self.quantity}"
