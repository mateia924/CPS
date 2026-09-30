import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.constants import (
    MONEY_DECIMAL_PLACES,
    MONEY_MAX_DIGITS,
    RATE_DECIMAL_PLACES,
    RATE_MAX_DIGITS,
)
from apps.common.models import DocumentStateMixin, TenantScopedModel


class Voucher(TenantScopedModel, DocumentStateMixin):
    """docs/SYSTEM_ANALYSIS.md 3.8 / docs/prompts/sprint-5.md block 5.3:
    the one engine behind سند قبض / سند صرف / سند تسوية. `status` comes
    from DocumentStateMixin — same DRAFT→PENDING_APPROVAL→APPROVED→
    POSTED→REVERSED vocabulary as JournalEntry (4.4) and Invoice (4.5).
    """

    class VoucherType(models.TextChoices):
        # Sprint 6 (block 6.0): labels match apps.approvals.models.
        # ApprovalRule.DocType's own wording exactly ("Receipt Voucher"
        # etc.) on purpose — same translated msgid, no collision with
        # apps.attachments.models.Attachment.Category.RECEIPT ("Receipt"
        # alone, a different concept translated differently).
        RECEIPT = "receipt", _("Receipt Voucher")
        PAYMENT = "payment", _("Payment Voucher")
        SETTLEMENT = "settlement", _("Settlement Voucher")

    class SettlementKind(models.TextChoices):
        INTERNAL_TRANSFER = "internal_transfer", _("Internal transfer")

    class TreasuryKind(models.TextChoices):
        BANK = "bank", _("Bank")
        CASH_BOX = "cash_box", _("Cash box")
        CUSTODY = "custody", _("Custody")

    class PartyRoleChoice(models.TextChoices):
        CUSTOMER = "customer", _("Customer")
        SUPPLIER = "supplier", _("Supplier")
        EMPLOYEE = "employee", _("Employee")
        AFFILIATE = "affiliate", _("Affiliate")

    class PaymentMethod(models.TextChoices):
        CASH = "cash", _("Cash")
        BANK_TRANSFER = "bank_transfer", _("Bank transfer")
        CHEQUE = "cheque", _("Cheque")
        CARD = "card", _("Card")
        OTHER = "other", _("Other")

    legal_entity = models.ForeignKey(
        "organization.LegalEntity", on_delete=models.PROTECT, related_name="vouchers"
    )
    voucher_type = models.CharField(_("voucher type"), max_length=10, choices=VoucherType.choices)
    settlement_kind = models.CharField(
        _("settlement kind"), max_length=20, choices=SettlementKind.choices, null=True, blank=True
    )
    # Sprint 5.0 decision 9 / D2 (owner): blank until the first exit
    # from DRAFT (services.py), never at creation — no gap from a
    # deleted draft.
    number = models.CharField(_("number"), max_length=32, blank=True)
    date = models.DateField(_("date"))

    currency = models.CharField(_("currency"), max_length=3)
    exchange_rate = models.DecimalField(
        _("exchange rate"), max_digits=RATE_MAX_DIGITS, decimal_places=RATE_DECIMAL_PLACES, default=1
    )
    exchange_rate_overridden = models.BooleanField(_("exchange rate overridden"), default=False)

    # Exactly one of bank/cash_box/custody is set, matching
    # treasury_kind — enforced in services.py (clean 400) and by a DB
    # CheckConstraint below as a second layer.
    treasury_kind = models.CharField(_("treasury kind"), max_length=10, choices=TreasuryKind.choices)
    bank = models.ForeignKey(
        "treasury.Bank", null=True, blank=True, on_delete=models.PROTECT, related_name="vouchers"
    )
    cash_box = models.ForeignKey(
        "treasury.CashBox", null=True, blank=True, on_delete=models.PROTECT, related_name="vouchers"
    )
    custody = models.ForeignKey(
        "treasury.Custody", null=True, blank=True, on_delete=models.PROTECT, related_name="vouchers"
    )

    # Sprint 5.4 (internal transfer only) — the destination treasury
    # account, same three-FK shape as above.
    counter_treasury_kind = models.CharField(
        _("counter treasury kind"), max_length=10, choices=TreasuryKind.choices, null=True, blank=True
    )
    counter_bank = models.ForeignKey(
        "treasury.Bank", null=True, blank=True, on_delete=models.PROTECT, related_name="counter_vouchers"
    )
    counter_cash_box = models.ForeignKey(
        "treasury.CashBox", null=True, blank=True, on_delete=models.PROTECT, related_name="counter_vouchers"
    )
    counter_custody = models.ForeignKey(
        "treasury.Custody", null=True, blank=True, on_delete=models.PROTECT, related_name="counter_vouchers"
    )
    # Only when the destination's currency differs from the source's —
    # the actual amount that arrived, in the destination's own currency
    # (decision 5.4: the implicit rate is logged as an override, no FX line).
    counter_amount_fc = models.DecimalField(
        _("counter amount"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES,
        null=True, blank=True,
    )

    # The single counterparty for this voucher (receipt: who paid us;
    # payment: who we paid) — every INVOICE/ON_ACCOUNT line resolves
    # against this same (party, party_role), matching the 5.6 UI's
    # single "استلمنا من"/"صرفنا إلى" field on the header, not per line.
    party = models.ForeignKey(
        "parties.Party", null=True, blank=True, on_delete=models.PROTECT, related_name="vouchers"
    )
    party_role = models.CharField(
        _("party role"), max_length=10, choices=PartyRoleChoice.choices, null=True, blank=True
    )
    # A payment voucher with no registered party (3.8: "بند مصروف
    # بضريبة مباشرة ... دون الحاجة لمورد مسجّل").
    payee_name = models.CharField(_("payee name"), max_length=255, blank=True)

    payment_method = models.CharField(
        _("payment method"), max_length=15, choices=PaymentMethod.choices, default=PaymentMethod.CASH
    )
    reference = models.CharField(_("reference"), max_length=100, blank=True)
    description = models.CharField(_("description"), max_length=255, blank=True)

    total_fc = models.DecimalField(
        _("total"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, default=0
    )
    total_base = models.DecimalField(
        _("total (base)"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, default=0
    )

    journal_entry = models.OneToOneField(
        "accounting.JournalEntry", null=True, blank=True, on_delete=models.SET_NULL, related_name="voucher"
    )
    # Sprint 5.5 (block 5.5.2): "سند من هذا البند" — a voucher created
    # from a bank statement line's own "create voucher" button carries
    # this through DRAFT/PENDING_APPROVAL, and _actually_post uses it to
    # auto-match the voucher's own bank-side journal line to it (a
    # best-effort match — a mismatch only warns, never blocks posting).
    source_statement_line = models.ForeignKey(
        "treasury.BankStatementLine", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    posted_at = models.DateTimeField(_("posted at"), null=True, blank=True)
    reversal_of = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="reversed_by"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    # Sprint 6.5.15 (UAT item 1): same grandfather flag as
    # JournalEntry.legacy_duplicate_number, added for uniformity across
    # every numbered document — the DB constraint below already caught
    # duplicate voucher numbers before this sprint (no live tenant has
    # ever had one), so a migration finding any to flag is expected to
    # be a no-op in practice.
    legacy_duplicate_number = models.BooleanField(_("legacy duplicate number"), default=False)

    class Meta:
        ordering = ["-date", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "number"],
                name="unique_voucher_number_per_tenant",
                condition=~models.Q(number="") & models.Q(legacy_duplicate_number=False),
            ),
            models.CheckConstraint(
                name="voucher_exactly_one_treasury_account",
                check=(
                    (models.Q(bank__isnull=False) & models.Q(cash_box__isnull=True) & models.Q(custody__isnull=True))
                    | (models.Q(bank__isnull=True) & models.Q(cash_box__isnull=False) & models.Q(custody__isnull=True))
                    | (models.Q(bank__isnull=True) & models.Q(cash_box__isnull=True) & models.Q(custody__isnull=False))
                ),
            ),
        ]
        # Sprint 6.6.3 (item 2): vouchers list/reconciliation-dashboard/
        # approval-queue filters.
        indexes = [
            models.Index(fields=["tenant", "legal_entity", "date"], name="vouchers_entity_date_idx"),
            models.Index(fields=["tenant", "status"], name="vouchers_status_idx"),
        ]

    def __str__(self):
        return self.number or f"({self.voucher_type} draft)"


class VoucherLine(models.Model):
    class LineType(models.TextChoices):
        INVOICE = "invoice", _("Invoice settlement")
        ON_ACCOUNT = "on_account", _("On account")
        ACCOUNT = "account", _("Direct account")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    voucher = models.ForeignKey(Voucher, on_delete=models.CASCADE, related_name="lines")
    line_no = models.PositiveIntegerField(_("line number"))
    line_type = models.CharField(_("line type"), max_length=10, choices=LineType.choices)

    # INVOICE
    invoice = models.ForeignKey(
        "sales.Invoice", null=True, blank=True, on_delete=models.PROTECT, related_name="voucher_lines"
    )
    allocated_invoice_fc = models.DecimalField(
        _("allocated (invoice currency)"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES,
        null=True, blank=True,
    )

    # ACCOUNT
    account = models.ForeignKey(
        "accounting.Account", null=True, blank=True, on_delete=models.PROTECT, related_name="voucher_lines"
    )
    tax_code = models.ForeignKey(
        "accounting.TaxCode", null=True, blank=True, on_delete=models.PROTECT, related_name="voucher_lines"
    )
    amount_includes_tax = models.BooleanField(_("amount includes tax"), default=False)
    tax_amount_fc = models.DecimalField(
        _("tax amount"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, default=0
    )
    # Optional audit-trail fields for a direct expense with no
    # registered supplier (3.8) — informational only, never posted.
    ext_supplier_name = models.CharField(_("supplier name"), max_length=255, blank=True)
    ext_supplier_tax_number = models.CharField(_("supplier tax number"), max_length=50, blank=True)
    ext_invoice_ref = models.CharField(_("supplier invoice ref"), max_length=100, blank=True)

    cost_center = models.ForeignKey(
        "organization.CostCenter", null=True, blank=True, on_delete=models.PROTECT, related_name="voucher_lines"
    )
    description = models.CharField(_("description"), max_length=255, blank=True)

    # Common to every line type — the voucher-currency amount this line
    # represents (for INVOICE: what got applied to the treasury side;
    # allocated_invoice_fc above is the separate invoice-currency amount).
    amount_fc = models.DecimalField(
        _("amount"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES
    )
    amount_base = models.DecimalField(
        _("amount (base)"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, default=0
    )
    tax_amount_base = models.DecimalField(
        _("tax amount (base)"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, default=0
    )

    class Meta:
        ordering = ["line_no"]

    def __str__(self):
        return f"{self.voucher} #{self.line_no}"


class VoucherAllocation(TenantScopedModel):
    """One per INVOICE-type VoucherLine — docs/prompts/sprint-5.md block
    5.3. Updates Invoice.paid_fc/balance_fc/payment_status when the
    voucher posts (services.post_voucher) and reverses them back when
    the voucher is reversed (is_reversed flips, the invoice fields are
    recomputed from its still-active allocations)."""

    voucher_line = models.OneToOneField(
        VoucherLine, on_delete=models.CASCADE, related_name="allocation"
    )
    invoice = models.ForeignKey(
        "sales.Invoice", on_delete=models.PROTECT, related_name="allocations"
    )
    allocated_invoice_fc = models.DecimalField(
        _("allocated (invoice currency)"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES
    )
    base_at_invoice_rate = models.DecimalField(
        _("base at invoice rate"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES
    )
    base_settled = models.DecimalField(
        _("base settled"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES
    )
    # base_settled - base_at_invoice_rate: on a RECEIPT, positive = a
    # realized FX gain (we collected more base-currency value than what
    # was booked); negative = a loss. Sign flips in meaning (not in
    # formula) for a PAYMENT, documented at the call site.
    fx_difference_base = models.DecimalField(
        _("FX difference (base)"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, default=0
    )
    is_reversed = models.BooleanField(_("reversed"), default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.invoice.number}: {self.allocated_invoice_fc}"
