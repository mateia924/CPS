from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.constants import (
    MONEY_DECIMAL_PLACES,
    MONEY_MAX_DIGITS,
    RATE_DECIMAL_PLACES,
    RATE_MAX_DIGITS,
)
from apps.common.models import TenantScopedModel


class Bank(TenantScopedModel):
    """docs/SYSTEM_ANALYSIS.md 3.3 section 2: registration only, no
    movements yet — `gl_account` is nullable-for-now, filled in
    automatically starting sprint 4 (same pattern as Party.gl_account)."""

    legal_entity = models.ForeignKey(
        "organization.LegalEntity", on_delete=models.PROTECT, related_name="banks"
    )
    name = models.CharField(_("name"), max_length=255)
    bank_name = models.CharField(_("bank name"), max_length=255, blank=True)
    account_number = models.CharField(_("account number"), max_length=64, blank=True)
    iban = models.CharField(_("IBAN"), max_length=34, blank=True)
    swift = models.CharField(_("SWIFT"), max_length=11, blank=True)
    currency = models.CharField(_("currency"), max_length=3, default="SAR")
    gl_account = models.ForeignKey(
        "accounting.Account", null=True, blank=True, on_delete=models.SET_NULL, related_name="banks"
    )
    is_active = models.BooleanField(_("active"), default=True)
    # Sprint 5.5 (block 5.5.1, v2 decision 5): the last successful
    # CSV/Excel column mapping for this bank's statement imports
    # ({"date": "...", "amount": "...", ...} or a debit/credit pair),
    # suggested back on the next import.
    import_column_mapping = models.JSONField(_("import column mapping"), default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class CashBox(TenantScopedModel):
    legal_entity = models.ForeignKey(
        "organization.LegalEntity", on_delete=models.PROTECT, related_name="cash_boxes"
    )
    name = models.CharField(_("name"), max_length=255)
    currency = models.CharField(_("currency"), max_length=3, default="SAR")
    # Optional (3.3 section 2) — an employee Party responsible for this
    # cash box. Validated in the serializer to actually hold the
    # EMPLOYEE role, not just be any party.
    custodian = models.ForeignKey(
        "parties.Party", null=True, blank=True, on_delete=models.PROTECT, related_name="cash_boxes"
    )
    gl_account = models.ForeignKey(
        "accounting.Account", null=True, blank=True, on_delete=models.SET_NULL, related_name="cash_boxes"
    )
    # docs/SYSTEM_ANALYSIS.md 3.3 ("الحد الأقصى للنقدية", an advanced
    # field documented since sprint 3 but never implemented until the
    # voucher engine — sprint 5.3 — actually needed it) — a WARNING
    # only (treasury_balance exceeding it doesn't block a voucher),
    # unlike Custody.limit_amount below (a hard 400 in sprint 5.4).
    max_balance = models.DecimalField(
        _("max cash balance"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES,
        null=True, blank=True,
    )
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "cash boxes"

    def __str__(self):
        return self.name


class ExchangeRate(TenantScopedModel):
    """Sprint 4.2 (docs/SYSTEM_ANALYSIS.md 3.11/3.15.3) — الخزينة ←
    "أسعار الصرف". `rate` converts 1 unit of `from_currency` into
    `to_currency` (e.g. from_currency=USD, to_currency=SAR, rate=3.75
    means 1 USD = 3.75 SAR). Never edited or deleted once created — an
    append-only historical record, same principle as a posted journal
    entry (services.get_rate always resolves the rate *as of* a given
    document date, so correcting a mistake means adding a new row, not
    changing history under an already-posted document)."""

    class Source(models.TextChoices):
        MANUAL = "manual", _("Manual")
        API = "api", _("API")

    from_currency = models.CharField(_("from currency"), max_length=3)
    to_currency = models.CharField(_("to currency"), max_length=3)
    date = models.DateField(_("date"))
    rate = models.DecimalField(_("rate"), max_digits=RATE_MAX_DIGITS, decimal_places=RATE_DECIMAL_PLACES)
    source = models.CharField(_("source"), max_length=10, choices=Source.choices, default=Source.MANUAL)
    created_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="exchange_rates"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "from_currency", "to_currency", "date"],
                name="unique_exchange_rate_per_pair_and_date",
            )
        ]

    def __str__(self):
        return f"{self.from_currency}->{self.to_currency} {self.date}: {self.rate}"


class BankStatement(TenantScopedModel):
    """Sprint 4.4 (docs/SYSTEM_ANALYSIS.md 3.15.2): schema only. Sprint
    5.5 (block 5.5.1, v2 decision 5) turns the single `statement_date`
    into a real period (`period_start`/`period_end`) — a statement
    covers a range of days, not one — and adds the fields the real
    import endpoint needs: `currency` (must match the bank's own),
    `import_format`, `file_sha256` (duplicate-file guard) and
    `line_count`/`imported_by` for the statements list screen.
    `source_file` (a bare path/filename, no real FileField) is
    superseded by storing the original upload as a real Attachment
    (`bank_statement` in ALLOWED_TARGETS) instead — kept, unused, since
    nothing has ever written to it (dev-only, zero rows)."""

    bank = models.ForeignKey(Bank, on_delete=models.PROTECT, related_name="statements")
    period_start = models.DateField(_("period start"))
    period_end = models.DateField(_("period end"))
    currency = models.CharField(_("currency"), max_length=3)
    opening_balance = models.DecimalField(
        _("opening balance"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, default=0
    )
    closing_balance = models.DecimalField(
        _("closing balance"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, default=0
    )
    import_format = models.CharField(_("import format"), max_length=10, blank=True)
    file_sha256 = models.CharField(_("file SHA-256"), max_length=64, blank=True)
    line_count = models.PositiveIntegerField(_("line count"), default=0)
    imported_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    source_file = models.CharField(_("source file"), max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-period_end"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "bank", "file_sha256"],
                condition=~models.Q(file_sha256=""),
                name="unique_statement_file_sha256_per_bank",
            )
        ]

    def __str__(self):
        return f"{self.bank} — {self.period_start}..{self.period_end}"


class BankStatementLine(TenantScopedModel):
    """Sprint 4.4: one row of an imported statement. Sprint 5.5 (block
    5.5.1/5.5.2, v2 decisions 2-3) replaces the plain `matched` boolean
    with a real three-way `status` the matching engine actually needs
    (a line can be legitimately outside the books, not just
    matched/unmatched)."""

    class Status(models.TextChoices):
        UNMATCHED = "unmatched", _("Unmatched")
        MATCHED = "matched", _("Matched")
        IGNORED = "ignored", _("Ignored")

    class MatchedBy(models.TextChoices):
        AUTO = "auto", _("Automatic")
        MANUAL = "manual", _("Manual")

    statement = models.ForeignKey(BankStatement, on_delete=models.CASCADE, related_name="lines")
    line_no = models.PositiveIntegerField(_("line number"), default=0)
    date = models.DateField(_("date"))
    # Signed: positive = deposit/credit on the statement, negative =
    # withdrawal/debit.
    amount = models.DecimalField(
        _("amount"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES
    )
    description = models.CharField(_("description"), max_length=255, blank=True)
    reference = models.CharField(_("reference"), max_length=100, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.UNMATCHED)
    matched_by = models.CharField(max_length=10, choices=MatchedBy.choices, blank=True)
    matched_by_user = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    matched_at = models.DateTimeField(null=True, blank=True)
    ignored_reason = models.CharField(_("ignored reason"), max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "line_no"]

    def __str__(self):
        return f"{self.date} {self.amount}"


class Custody(TenantScopedModel):
    """عهدة: cash advanced to a specific employee — unlike CashBox, the
    employee link is mandatory (3.3 section 2)."""

    legal_entity = models.ForeignKey(
        "organization.LegalEntity", on_delete=models.PROTECT, related_name="custodies"
    )
    employee = models.ForeignKey(
        "parties.Party", on_delete=models.PROTECT, related_name="custodies"
    )
    name = models.CharField(_("name"), max_length=255)
    currency = models.CharField(_("currency"), max_length=3, default="SAR")
    gl_account = models.ForeignKey(
        "accounting.Account", null=True, blank=True, on_delete=models.SET_NULL, related_name="custodies"
    )
    # docs/SYSTEM_ANALYSIS.md 3.3 ("حد العهدة") — a hard 400 in sprint
    # 5.4 (custody transfers), unlike CashBox.max_balance above.
    limit_amount = models.DecimalField(
        _("custody limit"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES,
        null=True, blank=True,
    )
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "custodies"

    def __str__(self):
        return self.name


class CashCount(TenantScopedModel):
    """Sprint 5.5 (block 5.5.3, CFO_REVIEW_1 F14) — "جرد الصندوق": a
    physical cash count against the book balance, same auditor-control
    logic as bank reconciliation (v2 decision 8). `book_balance_snapshot`
    is computed once at creation (from treasury_balance(as_of=count_date,
    end of day)) and never recomputed — a genuine point-in-time snapshot,
    not a live value."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        CONFIRMED = "confirmed", _("Confirmed")

    cash_box = models.ForeignKey(CashBox, on_delete=models.PROTECT, related_name="counts")
    number = models.CharField(_("number"), max_length=30, blank=True)
    count_date = models.DateField(_("count date"))
    counted_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="+"
    )
    # Optional denomination breakdown — {"500": 2, "100": 5, ...} — used
    # only to compute counted_amount when given; a mismatch against a
    # separately-supplied counted_amount is rejected (v2 decision 8).
    denominations = models.JSONField(_("denominations"), default=dict, blank=True)
    counted_amount = models.DecimalField(
        _("counted amount"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES
    )
    book_balance_snapshot = models.DecimalField(
        _("book balance snapshot"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES
    )
    difference = models.DecimalField(
        _("difference"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES
    )
    reason = models.TextField(_("reason"), blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    confirmed_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    variance_voucher = models.ForeignKey(
        "vouchers.Voucher", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-count_date", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "number"], name="unique_cash_count_number_per_tenant",
                condition=~models.Q(number=""),
            )
        ]

    def __str__(self):
        return f"{self.cash_box} — {self.count_date}"


class IbanChangeRequest(TenantScopedModel):
    """Sprint 5.5 (block 5.5.0, CFO_REVIEW_1 C10, SYSTEM_ANALYSIS.md
    3.15.9): the only path a *non-empty* Bank.iban or Party.iban may
    change through (first entry on an empty field is a plain edit — see
    apps.common.serializers.validate_iban_field). Uses the exact same
    generic status vocabulary as apps.approvals.services
    (STATUS_DRAFT/STATUS_PENDING_APPROVAL/STATUS_APPROVED) so it can run
    through submit_for_approval/approve/reject/withdraw unmodified, with
    a fixed doc_type=IBAN_CHANGE rule (min_amount=0, required_role=
    Owner) seeded for every tenant — see
    access/migrations and approvals/migrations for this sprint."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        PENDING_APPROVAL = "pending_approval", _("Pending approval")
        APPROVED = "approved", _("Approved")

    # GenericFK target, restricted to Bank/Party only by the serializer
    # (never a raw client-supplied app_label/model — same discipline as
    # apps.attachments.services.ALLOWED_TARGETS).
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="+")
    object_id = models.UUIDField()
    target = GenericForeignKey("content_type", "object_id")

    old_iban = models.CharField(_("old IBAN"), max_length=34, blank=True)
    new_iban = models.CharField(_("new IBAN"), max_length=34)
    reason = models.TextField(_("reason"))
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    # Named `created_by` (not `requested_by`) so this model satisfies
    # the shared approvals engine's assumption
    # (apps.approvals.services.approve/withdraw both read
    # document.created_by_id directly) — same field name every other
    # approvable document (JournalEntry, Invoice, Voucher) already uses.
    created_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="iban_change_requests"
    )
    decided_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"IBAN change for {self.content_type.model} {self.object_id}: {self.old_iban} -> {self.new_iban}"
