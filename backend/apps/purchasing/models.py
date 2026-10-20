from decimal import Decimal

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
from apps.common.models import DocumentStateMixin, SoftDeleteModelMixin, TenantScopedModel


class PurchaseSettings(models.Model):
    """Sprint 8.0 — one row per tenant, same aux-table shape as
    apps.inventory.models.InventorySettings (plain Model, OneToOneField,
    created lazily by PurchaseSettingsView, never at registration).

    R-8.5: the three-way match tolerance. A bill line whose price
    differs from its receipt by more than BOTH limits needs
    `purchasing.override_match` and a recorded reason (8.5). The
    defaults are S4's proposal (2% / 50 in the base currency), not
    numbers any posting code carries — they live here only.

    `default_grni_policy`: how a bill/receipt price difference settles
    GRNI (8.5). sprint-8.md names the field but defines only one
    behaviour, R-8.1 (binding): to the item's cost for the quantity still
    in stock, the issued part to PURCHASE_PRICE_VARIANCE by ratio. So it
    has one member today; a second is an owner decision, not a guess."""

    class GrniPolicy(models.TextChoices):
        PRORATE_TO_COST_AND_VARIANCE = "prorate", _("Item cost for stock on hand, variance for the issued part")

    tenant = models.OneToOneField(
        "tenants.Tenant", on_delete=models.CASCADE, related_name="purchase_settings"
    )
    match_tolerance_pct = models.DecimalField(
        _("match tolerance (%)"), max_digits=PERCENTAGE_MAX_DIGITS, decimal_places=PERCENTAGE_DECIMAL_PLACES,
        default=Decimal("2.00"),
    )
    match_tolerance_amount = models.DecimalField(
        _("match tolerance (base currency)"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES,
        default=Decimal("50.00"),
    )
    default_grni_policy = models.CharField(
        _("GRNI settlement policy"), max_length=20, choices=GrniPolicy.choices,
        default=GrniPolicy.PRORATE_TO_COST_AND_VARIANCE,
    )

    class Meta:
        verbose_name = _("purchase settings")
        verbose_name_plural = _("purchase settings")

    def __str__(self):
        return f"purchase settings for {self.tenant_id}"


class WithholdingTaxCode(TenantScopedModel):
    """Sprint 8.0 (D6): withholding tax is data per country, never a rate
    in code (sprint-8.md §0 rule 2). Seeded per tenant from
    apps/compliance/<country>/withholding.json by
    apps.purchasing.services.load_withholding_codes — the same per-tenant
    shape as accounting.TaxCode and its tax_codes.json.

    `is_example`: every code loaded from the JSON starts True ("أمثلة —
    راجع استشاريك") and stays True until the owner approves the country's
    table (S2). The loader never touches an existing row, so neither that
    approval nor an edited rate is ever undone by a re-run.

    `base`: what the rate applies to — the line's amount before VAT (NET)
    or including it (GROSS). `applies_to`: which suppliers may carry the
    code (PartyRole.is_resident); 8.3 rejects a mismatch."""

    class Base(models.TextChoices):
        NET = "net", _("Net (before VAT)")
        GROSS = "gross", _("Gross (including VAT)")

    class AppliesTo(models.TextChoices):
        RESIDENT = "resident", _("Resident suppliers")
        NON_RESIDENT = "non_resident", _("Non-resident suppliers")
        BOTH = "both", _("Both")

    country = models.CharField(_("country"), max_length=2)
    code = models.CharField(_("code"), max_length=20)
    name_ar = models.CharField(_("name"), max_length=100)
    rate = models.DecimalField(_("rate (%)"), max_digits=PERCENTAGE_MAX_DIGITS, decimal_places=PERCENTAGE_DECIMAL_PLACES)
    base = models.CharField(_("base"), max_length=10, choices=Base.choices)
    applies_to = models.CharField(_("applies to"), max_length=15, choices=AppliesTo.choices)
    is_example = models.BooleanField(_("example, not yet approved"), default=True)
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["country", "code"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "country", "code"], name="unique_wht_code_per_tenant_country"),
        ]

    def __str__(self):
        return f"{self.country}/{self.code}"


def _money(verbose):
    return models.DecimalField(
        verbose, max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, default=Decimal("0")
    )


class SupplierBill(TenantScopedModel, DocumentStateMixin, SoftDeleteModelMixin):
    """Sprint 8.1: فاتورة المورد — service, expense and asset lines (stock
    lines arrive in 8.5). The unified status set as it really is
    (apps.common.models.DocumentStateMixin): DRAFT -> PENDING_APPROVAL ->
    APPROVED -> POSTED -> REVERSED; a rejection returns to DRAFT
    (apps.approvals.services.reject), so there is no "rejected" value.

    `bill_number` is the SUPPLIER's own invoice number — required, unique
    per supplier among bills not deleted. `number` is ours (PINV), given
    when the bill first leaves DRAFT, same convention as invoices.

    Totals are server-side (apps.purchasing.bills.recalculate_bill), in
    the bill's currency:
      subtotal          Σ line net
      deductible_tax    Σ VAT that goes to VAT_INPUT
      capitalized_tax   Σ non-deductible VAT folded into the line's cost (R-8.6)
      reverse_charge_tax Σ RC VAT — self-assessed both sides, not owed to the supplier
      wht_expected      Σ expected withholding — shown only; it posts at payment (8.3)
      total             what the supplier is owed (subtotal + deductible + capitalized)
    "المستحق" is `total` in 8.1: pay-now and allocation ship in 8.2.

    Not in 8.1 (D3 fields that cannot exist yet): grn_line (GoodsReceipt is
    8.4), kind=DEBIT_NOTE/original_bill (8.7), payment_now (8.2, with the
    generalized allocation)."""

    legal_entity = models.ForeignKey("organization.LegalEntity", on_delete=models.PROTECT, related_name="supplier_bills")
    supplier = models.ForeignKey("parties.Party", on_delete=models.PROTECT, related_name="supplier_bills")
    bill_number = models.CharField(_("supplier invoice number"), max_length=64)
    number = models.CharField(_("number"), max_length=32, blank=True, default="")
    date = models.DateField(_("date"))
    due_date = models.DateField(_("due date"), null=True, blank=True)
    currency = models.CharField(_("currency"), max_length=3)
    exchange_rate = models.DecimalField(
        _("exchange rate"), max_digits=RATE_MAX_DIGITS, decimal_places=RATE_DECIMAL_PLACES, default=Decimal("1")
    )
    reference = models.CharField(_("reference"), max_length=100, blank=True)
    notes = models.TextField(_("notes"), blank=True)

    subtotal = _money(_("subtotal"))
    deductible_tax = _money(_("deductible VAT"))
    capitalized_tax = _money(_("non-deductible VAT (capitalized)"))
    reverse_charge_tax = _money(_("reverse-charge VAT"))
    wht_expected = _money(_("expected withholding"))
    total = _money(_("total"))
    base_total = _money(_("total in base currency"))

    journal_entry = models.OneToOneField(
        "accounting.JournalEntry", null=True, blank=True, on_delete=models.SET_NULL, related_name="supplier_bill"
    )
    created_by = models.ForeignKey("accounts.User", null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "number"], condition=~models.Q(number=""), name="unique_supplier_bill_number_per_tenant"
            ),
            models.UniqueConstraint(
                fields=["tenant", "supplier", "bill_number"], condition=models.Q(deleted_at__isnull=True),
                name="unique_supplier_invoice_number_per_supplier",
            ),
        ]
        indexes = [models.Index(fields=["tenant", "legal_entity", "date"]), models.Index(fields=["tenant", "status"])]

    def __str__(self):
        return self.number or f"{self.supplier_id}/{self.bill_number}"


class SupplierBillLine(models.Model):
    """One line of a supplier bill. The line type decides which fields
    apply (D12): SERVICE -> description + account; EXPENSE -> account +
    cost center; ASSET -> asset name + category (the account is always
    FIXED_ASSETS, R-8.7). STOCK is 8.5.

    VAT: `tax_code` per line, and `vat_deductible`. The VAT is
    non-deductible when either says so (the switch off, or a code whose
    own `deductible` is NONE, like the seeded SN) and is then folded into
    the line's cost (R-8.6). A REVERSE_CHARGE code self-assesses: output
    and input at the same amount, nothing owed to the supplier for it.

    Computed by recalculate_bill, never accepted from a client: net,
    tax_amount, capitalized_tax, cost (what the debit line carries),
    payable (what the supplier is owed for this line), wht_base/wht_amount.
    `asset` is set at posting for an ASSET line."""

    class LineType(models.TextChoices):
        SERVICE = "service", _("Service")
        EXPENSE = "expense", _("Expense")
        ASSET = "asset", _("Fixed asset")

    bill = models.ForeignKey(SupplierBill, on_delete=models.CASCADE, related_name="lines")
    line_no = models.PositiveIntegerField()
    line_type = models.CharField(_("line type"), max_length=10, choices=LineType.choices)
    description = models.CharField(_("description"), max_length=255, blank=True)
    account = models.ForeignKey("accounting.Account", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    cost_center = models.ForeignKey(
        "organization.CostCenter", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    qty = models.DecimalField(
        _("quantity"), max_digits=QUANTITY_MAX_DIGITS, decimal_places=QUANTITY_DECIMAL_PLACES, default=Decimal("1")
    )
    unit_price = models.DecimalField(_("unit price"), max_digits=PRICE_MAX_DIGITS, decimal_places=PRICE_DECIMAL_PLACES)
    tax_code = models.ForeignKey("accounting.TaxCode", on_delete=models.PROTECT, related_name="+")
    vat_deductible = models.BooleanField(_("VAT deductible"), default=True)
    wht_code = models.ForeignKey(WithholdingTaxCode, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    asset_name = models.CharField(_("asset name"), max_length=255, blank=True)
    asset_category = models.CharField(_("asset category"), max_length=20, blank=True)
    asset = models.OneToOneField(
        "assets.Asset", null=True, blank=True, on_delete=models.PROTECT, related_name="source_bill_line"
    )

    net = _money(_("net"))
    tax_amount = _money(_("VAT"))
    capitalized_tax = _money(_("capitalized VAT"))
    cost = _money(_("cost"))
    payable = _money(_("payable"))
    wht_base = _money(_("withholding base"))
    wht_amount = _money(_("expected withholding"))

    class Meta:
        ordering = ["line_no"]

    def __str__(self):
        return f"{self.bill_id}#{self.line_no}"


class AdvanceApplication(TenantScopedModel):
    """Sprint 8.2 (D7): applying a supplier advance to a supplier bill, "من
    شاشة الفاتورة". The advance is a posted payment-voucher line: ADVANCE
    (on SUPPLIER_ADVANCES) or ON_ACCOUNT (on the supplier's current account),
    the accountant's choice per D7. Not a VoucherAllocation: that table is
    one row per voucher line (OneToOne), and one advance may be spread over
    several bills.

    Same currency only (advance and bill). The journal entry
    (apps.purchasing.payments.apply_advance):
      ADVANCE    Dr supplier at the bill's rate / Cr SUPPLIER_ADVANCES at the
                 advance's rate, the base difference on FX_REALIZED;
      ON_ACCOUNT the debit already sits on the supplier's account, so only a
                 base difference between the two rates is booked (none at
                 rate 1 — then no entry at all).
    Withdrawing it reverses that entry and sets is_reversed; a bill's balance
    and an advance's remainder count only rows that are not reversed."""

    source_line = models.ForeignKey("vouchers.VoucherLine", on_delete=models.PROTECT, related_name="advance_applications")
    supplier_bill = models.ForeignKey(SupplierBill, on_delete=models.PROTECT, related_name="advance_applications")
    date = models.DateField(_("date"))
    amount_fc = models.DecimalField(_("amount"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES)
    base_at_bill_rate = _money(_("base at the bill's rate"))
    base_at_advance_rate = _money(_("base at the advance's rate"))
    fx_difference_base = _money(_("FX difference (base)"))
    journal_entry = models.OneToOneField(
        "accounting.JournalEntry", null=True, blank=True, on_delete=models.SET_NULL, related_name="advance_application"
    )
    is_reversed = models.BooleanField(_("withdrawn"), default=False)
    created_by = models.ForeignKey("accounts.User", null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount_fc__gt=0), name="advance_application_amount_positive"),
        ]

    def __str__(self):
        return f"{self.source_line_id} -> {self.supplier_bill_id}: {self.amount_fc}"
