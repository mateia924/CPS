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
    """Sprint 4.4 (docs/SYSTEM_ANALYSIS.md 3.15.2): schema only — import
    (CSV/Excel/MT940/CAMT.053), matching and the reconciliation report
    are sprint 5.5. `source_file` is a plain path/filename for now (no
    upload endpoint yet, no storage backend configured in this
    project) rather than a real FileField, to avoid introducing S3/
    media-storage config before 5.5 actually needs it."""

    bank = models.ForeignKey(Bank, on_delete=models.PROTECT, related_name="statements")
    statement_date = models.DateField(_("statement date"))
    opening_balance = models.DecimalField(
        _("opening balance"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, default=0
    )
    closing_balance = models.DecimalField(
        _("closing balance"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, default=0
    )
    source_file = models.CharField(_("source file"), max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-statement_date"]

    def __str__(self):
        return f"{self.bank} — {self.statement_date}"


class BankStatementLine(TenantScopedModel):
    """Sprint 4.4: one row of an imported statement — matching
    (`matched`) is set by the sprint 5.5 engine, not here."""

    statement = models.ForeignKey(BankStatement, on_delete=models.CASCADE, related_name="lines")
    date = models.DateField(_("date"))
    # Signed: positive = deposit/credit on the statement, negative =
    # withdrawal/debit.
    amount = models.DecimalField(
        _("amount"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES
    )
    description = models.CharField(_("description"), max_length=255, blank=True)
    reference = models.CharField(_("reference"), max_length=100, blank=True)
    matched = models.BooleanField(_("matched"), default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date"]

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
