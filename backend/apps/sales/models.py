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
    # Sprint 4.6 (3.16.2, rule 16): pre-fills a new invoice line's
    # tax_code — the free tax_rate above stays as-is (a product-level
    # default/legacy display value), it no longer drives what actually
    # posts; InvoiceLine.tax_code does.
    default_tax_code = models.ForeignKey(
        "accounting.TaxCode", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
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
        # Sprint 4.5 (3.15.1): the same two intermediate values every
        # approvable document uses (apps.approvals.services) — Invoice
        # keeps its own field/choices rather than literally inheriting
        # DocumentStateMixin, since its terminal states (issued/paid/
        # cancelled) don't fit that mixin's vocabulary; see the Decision
        # Log. "ISSUED(=POSTED)" in the sprint spec: an approved invoice
        # transitions straight to ISSUED (no separate "posted" value for
        # invoices — issuing IS posting here, unchanged since sprint 1).
        PENDING_APPROVAL = "pending_approval", _("Pending approval")
        APPROVED = "approved", _("Approved")
        ISSUED = "issued", _("Issued")
        PAID = "paid", _("Paid")
        CANCELLED = "cancelled", _("Cancelled")

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", _("Unpaid")
        PARTIAL = "partial", _("Partially paid")
        PAID = "paid", _("Paid")

    # Sprint 3 (3.3): superseded by `party` below (FK to parties.Party,
    # role=CUSTOMER) — kept, untouched, purely for historical reference;
    # no code reads or writes this field going forward. See the Decision
    # Log for why the column is kept rather than dropped.
    legacy_customer = models.ForeignKey(
        Customer, null=True, blank=True, on_delete=models.PROTECT, related_name="invoices"
    )
    party = models.ForeignKey("parties.Party", on_delete=models.PROTECT, related_name="invoices")
    # Sprint 4.5: segregation of duties needs to know who drafted this
    # invoice — null for every pre-4.5 row.
    created_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # Mandatory per docs/SYSTEM_ANALYSIS.md section 4 rule 3. Went
    # through the 3-step safe migration for pre-sprint-1 rows: nullable,
    # backfill, then NOT NULL (apps/sales/migrations/0002-0004).
    legal_entity = models.ForeignKey(
        "organization.LegalEntity", on_delete=models.PROTECT, related_name="invoices"
    )
    # Sprint 5.7 (CFO_REVIEW_1 C6 / decision D2): blank until the first
    # exit from DRAFT (issue_invoice), not at create time — a deleted
    # draft must never leave a gap in the sequence. Same pattern as
    # Voucher.number (5.0/5.3).
    number = models.CharField(_("number"), max_length=32, blank=True, default="")
    status = models.CharField(_("status"), max_length=20, choices=Status.choices, default=Status.DRAFT)
    issue_date = models.DateField(_("issue date"))
    # Sprint 5.0 (prompt block 5.0 item 5): derived once at create/update
    # time from the customer's payment_terms_days (PartyRole.details) —
    # null when the customer has no payment terms set. Purely
    # informational until vouchers (5.3) actually use it for aging.
    due_date = models.DateField(_("due date"), null=True, blank=True)

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
    # Sprint 5.0/5.3 (prompt block 5.0 item 5): kept in the invoice's
    # own currency, updated server-side only from VoucherAllocation
    # (5.3) — never accepted as API input. Every pre-5.0 invoice
    # backfills to paid_fc=0, balance_fc=total, payment_status=UNPAID
    # (nothing could have been allocated before this sprint existed).
    paid_fc = models.DecimalField(
        _("paid"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, default=0
    )
    balance_fc = models.DecimalField(
        _("balance"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, default=0
    )
    payment_status = models.CharField(
        _("payment status"), max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID
    )
    # Sprint 5.6 (block 5.6, print page): set once, the first time the
    # invoice is printed or downloaded — never cleared, never updated
    # again. Purely informational this sprint; CFO_REVIEW_1 C7 (not yet
    # built) will use it as a guard against cancelling an invoice the
    # customer has already seen.
    delivered_at = models.DateTimeField(_("delivered at"), null=True, blank=True)
    # Sprint 6.7 (decision 14, CFO_REVIEW_1 C7): the guard delivered_at
    # was reserved for — set when this invoice was voided despite
    # already being delivered (`sales.void_delivered_invoice` + a
    # mandatory reason). A documented temporary override until sprint
    # 9's creditor notices exist, at which point that permission is
    # removed entirely (see the Decision Log).
    is_post_delivery_void = models.BooleanField(_("voided after delivery"), default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Sprint 6.5.15 (UAT item 1): same grandfather flag as
    # JournalEntry.legacy_duplicate_number, added for uniformity — the
    # constraint below already caught duplicate invoice numbers before
    # this sprint (no live tenant has ever had one), so a migration
    # finding any to flag is expected to be a no-op in practice.
    legacy_duplicate_number = models.BooleanField(_("legacy duplicate number"), default=False)

    class Meta:
        ordering = ["-issue_date", "-created_at"]
        constraints = [
            # Correction after 4.1 (Decision Log, SYSTEM_ANALYSIS.md
            # §11): reverted to tenant-wide uniqueness — ZATCA requires
            # a unique invoice number per tax registration, and
            # branches normally share one tax number under the same
            # tenant, so "INV-2026-00001" issued by two different
            # branches would violate that even though this project's
            # own DB allowed it. apps.numbering.services.
            # next_document_number now folds the branch's code into the
            # string whenever the tenant has more than one branch/
            # company, so the sequence can still stay scoped per
            # legal_entity without two branches' numbers colliding as
            # text.
            models.UniqueConstraint(
                fields=["tenant", "number"],
                name="unique_invoice_number_per_tenant",
                condition=~models.Q(number="") & models.Q(legacy_duplicate_number=False),
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
    # Sprint 4.6 (3.16.2, rule 16): "البند يحمل tax_code (FK) لا نسبة
    # حرّة" — tax_rate above becomes a pure snapshot computed from
    # tax_code.rate at save time (services._build_lines), not a free
    # input anymore. Nullable-then-required 3-step migration (same
    # pattern as Invoice.legal_entity): nullable here, backfilled
    # (15% -> S, 0% -> Z) by a data migration, then a follow-up
    # migration makes it NOT NULL.
    tax_code = models.ForeignKey(
        "accounting.TaxCode", on_delete=models.PROTECT, related_name="invoice_lines"
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
