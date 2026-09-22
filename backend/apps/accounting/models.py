import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.constants import (
    MONEY_DECIMAL_PLACES,
    MONEY_MAX_DIGITS,
    RATE_DECIMAL_PLACES,
    RATE_MAX_DIGITS,
)
from apps.common.models import TenantScopedModel


class Account(TenantScopedModel):
    """Sprint 4.3 (ARCH_REVIEW_1.md §3.1): partial rebuild — `code`,
    `name`, `type`, `is_system` are unchanged from before; `parent`
    follows the exact same self-FK/cycle-check pattern already proven
    by LegalEntity/CostCenter (apps/organization/models.py)."""

    class Type(models.TextChoices):
        ASSET = "asset", _("Asset")
        LIABILITY = "liability", _("Liability")
        EQUITY = "equity", _("Equity")
        REVENUE = "revenue", _("Revenue")
        EXPENSE = "expense", _("Expense")

    class NormalBalance(models.TextChoices):
        DEBIT = "debit", _("Debit")
        CREDIT = "credit", _("Credit")

    # Type -> its normal_balance when not explicitly overridden (contra
    # accounts, e.g. accumulated depreciation under ASSET, need CREDIT —
    # hence normal_balance is a real, overridable field, not purely
    # derived).
    _DEFAULT_NORMAL_BALANCE_BY_TYPE = {
        Type.ASSET: NormalBalance.DEBIT,
        Type.EXPENSE: NormalBalance.DEBIT,
        Type.LIABILITY: NormalBalance.CREDIT,
        Type.EQUITY: NormalBalance.CREDIT,
        Type.REVENUE: NormalBalance.CREDIT,
    }

    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )
    # Computed in save() from parent.level + 1 — never set directly.
    level = models.PositiveIntegerField(default=0, editable=False)
    code = models.CharField(_("code"), max_length=20)
    name = models.CharField(_("name"), max_length=255)
    type = models.CharField(_("type"), max_length=20, choices=Type.choices)
    normal_balance = models.CharField(
        _("normal balance"), max_length=10, choices=NormalBalance.choices, blank=True, default=""
    )
    # Meaningful (and enforced — see can_post) only on leaf accounts; a
    # non-leaf account never allows posting regardless of this flag.
    allow_posting = models.BooleanField(_("allow posting"), default=True)
    is_intercompany = models.BooleanField(_("intercompany"), default=False)
    # The sub-ledger/running account for a Party (3.4: "حسابات جاري
    # تلقائية للأطراف") — a Party with two roles (customer + supplier)
    # gets two separate Account rows, both pointing here at the same
    # Party (one under CUSTOMERS, one under SUPPLIERS); see
    # apps.accounting.services.get_or_create_party_role_account.
    # Supersedes the single Party.gl_account field from sprint 3, which
    # can't represent "one party, two accounts" — kept, untouched,
    # unused going forward (Decision Log).
    party = models.ForeignKey(
        "parties.Party", null=True, blank=True, on_delete=models.PROTECT, related_name="gl_accounts"
    )
    # Tags a template-seeded account for lookup by meaning instead of by
    # hardcoded code (3.4: "الكود يشير للحساب عبر system_key لا عبر
    # الرقم") — blank for any account a user adds by hand.
    system_key = models.CharField(_("system key"), max_length=30, blank=True, default="")
    is_system = models.BooleanField(_("system account"), default=False)
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="unique_account_code_per_tenant")
        ]

    def __str__(self):
        return f"{self.code} {self.name}"

    @property
    def is_leaf(self):
        return not self.children.exists()

    @property
    def can_post(self):
        """3.4 rule: "لا ترحيل على حساب له أبناء" — a non-leaf account
        never allows posting, regardless of allow_posting's stored
        value (that flag only means something on a leaf)."""
        return self.is_leaf and self.allow_posting

    def clean(self):
        if not self.parent_id:
            return
        if self.parent_id == self.id:
            raise ValidationError(_("An account cannot be its own parent."))
        if self.parent.type != self.type:
            raise ValidationError(_("An account must have the same type as its parent."))
        node = self.parent
        seen = set()
        while node is not None:
            if node.id == self.id or node.id in seen:
                raise ValidationError(_("This would create a cycle in the chart of accounts."))
            seen.add(node.id)
            node = node.parent

    def save(self, *args, **kwargs):
        if not self.normal_balance:
            self.normal_balance = self._DEFAULT_NORMAL_BALANCE_BY_TYPE[self.type]
        self.level = (self.parent.level + 1) if self.parent_id else 0
        super().save(*args, **kwargs)


class JournalEntry(TenantScopedModel):
    # Same 3-step migration story as Invoice.legal_entity — see
    # apps/accounting/migrations/0002-0004.
    legal_entity = models.ForeignKey(
        "organization.LegalEntity", on_delete=models.PROTECT, related_name="journal_entries"
    )
    date = models.DateField(_("date"))
    memo = models.CharField(_("memo"), max_length=255, blank=True)
    source_type = models.CharField(_("source type"), max_length=50, blank=True)
    source_id = models.UUIDField(_("source id"), null=True, blank=True)
    # Sprint 4.2 (3.11/3.15.3): the entry's transaction currency and the
    # single rate that converts every line's *_fc amount into the
    # legal_entity's base currency (JournalLine.debit/credit). Defaults
    # keep every pre-4.2 entry and every same-currency entry unchanged
    # (currency=base, rate=1) — see the migration backfill.
    currency = models.CharField(_("currency"), max_length=3, default="SAR")
    exchange_rate = models.DecimalField(
        _("exchange rate"), max_digits=RATE_MAX_DIGITS, decimal_places=RATE_DECIMAL_PLACES, default=1
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.date} {self.memo}"


class JournalLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name="lines")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="journal_lines")
    cost_center = models.ForeignKey(
        "organization.CostCenter",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="journal_lines",
    )
    # Sprint 4.3 (3.4): auto-filled when posting to a sub-ledger account
    # (account.party is set) — for statements/aging later (3.16.1's
    # drill-down, sprint 10). Never a user-facing input.
    party = models.ForeignKey(
        "parties.Party", null=True, blank=True, on_delete=models.PROTECT, related_name="journal_lines"
    )
    # Base-currency amounts (legal_entity.base_currency) — unchanged
    # meaning from before 4.2, still what balance sheets/trial balances
    # read.
    debit = models.DecimalField(max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, default=0)
    credit = models.DecimalField(max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, default=0)
    # Transaction-currency amounts (entry.currency) — sprint 4.2. Equal
    # to debit/credit whenever entry.currency == base currency (rate 1).
    debit_fc = models.DecimalField(
        max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, default=0
    )
    credit_fc = models.DecimalField(
        max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, default=0
    )

    def __str__(self):
        return f"{self.account.code} D{self.debit} C{self.credit}"
