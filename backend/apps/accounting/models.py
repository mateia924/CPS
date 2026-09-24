import uuid

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.constants import (
    MONEY_DECIMAL_PLACES,
    MONEY_MAX_DIGITS,
    PERCENTAGE_DECIMAL_PLACES,
    PERCENTAGE_MAX_DIGITS,
    RATE_DECIMAL_PLACES,
    RATE_MAX_DIGITS,
)
from apps.common.models import DocumentStateMixin, TenantScopedModel


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
    # CFO_REVIEW_1 C2: a control account (sub-ledger for a party, a
    # bank/cash-box/custody's own gl_account, or a system tax/FX/
    # rounding/opening-balance/retained-earnings account) never takes a
    # direct manual JV line — only its own source document (invoice,
    # voucher, ...) may post to it — except through an explicit,
    # logged override. See apps.accounting.services.create_manual_
    # journal_entry and the migration backfilling this for every
    # existing tenant's chart.
    allow_manual_posting = models.BooleanField(_("allow manual posting"), default=True)
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
        value (that flag only means something on a leaf). CFO_REVIEW_1
        C13: a deactivated account never accepts a posting either,
        regardless of who's posting (manual JV, invoice, voucher — this
        is the one check every posting path already funnels through)."""
        return self.is_leaf and self.allow_posting and self.is_active

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


class JournalEntry(TenantScopedModel, DocumentStateMixin):
    # Same 3-step migration story as Invoice.legal_entity — see
    # apps/accounting/migrations/0002-0004.
    legal_entity = models.ForeignKey(
        "organization.LegalEntity", on_delete=models.PROTECT, related_name="journal_entries"
    )
    date = models.DateField(_("date"))
    memo = models.CharField(_("memo"), max_length=255, blank=True)
    # Sprint 4.1: JV numbering (apps.numbering) — blank for the rare
    # pre-4.4 row a migration couldn't safely backfill (none expected in
    # practice; every entry created going forward always gets one).
    number = models.CharField(_("number"), max_length=32, blank=True, default="")
    reference = models.CharField(_("reference"), max_length=100, blank=True)
    # Sprint 4.4 (3.15.1): who drafted this entry — null for every
    # system-generated entry (post_invoice_journal_entry/
    # void_invoice_journal_entry create no human actor) and for every
    # pre-4.4 row. Used for segregation of duties: the creator of a
    # manual entry can never also be the one who approves it.
    created_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # A reversal entry points back at the entry it reverses — the
    # original stays discoverable via reverses.reversed_by (sprint 4.4:
    # "قيدًا عكسيًا POSTED مرتبطًا بالأصل").
    reverses = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversed_by"
    )
    # Kept, untouched, unused going forward — superseded by
    # content_type/object_id below (a real GenericFK, ARCH_REVIEW_1.md
    # debt #6: "source_type/source_id نص حر لا GenericFK حقيقي"). Same
    # never-delete-a-column pattern as Invoice.legacy_customer.
    source_type = models.CharField(_("source type"), max_length=50, blank=True)
    source_id = models.UUIDField(_("source id"), null=True, blank=True)
    content_type = models.ForeignKey(
        ContentType, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    object_id = models.UUIDField(null=True, blank=True)
    source = GenericForeignKey("content_type", "object_id")
    # Sprint 4.2 (3.11/3.15.3): the entry's transaction currency and the
    # single rate that converts every line's *_fc amount into the
    # legal_entity's base currency (JournalLine.debit/credit). Defaults
    # keep every pre-4.2 entry and every same-currency entry unchanged
    # (currency=base, rate=1) — see the migration backfill.
    currency = models.CharField(_("currency"), max_length=3, default="SAR")
    exchange_rate = models.DecimalField(
        _("exchange rate"), max_digits=RATE_MAX_DIGITS, decimal_places=RATE_DECIMAL_PLACES, default=1
    )
    # CFO_REVIEW_1 C1: the one other column (besides status) a POSTED
    # row is allowed to change on its POSTED->REVERSED transition — the
    # DB trigger's exception list names it explicitly.
    reversed_at = models.DateTimeField(_("reversed at"), null=True, blank=True)
    # CFO_REVIEW_1 C2: set when this entry's posting overrode at least
    # one control-account line — override_reason itself lives only in
    # AuditLog (log_action), not duplicated as a column here.
    is_control_override = models.BooleanField(_("control override"), default=False)
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
    # "بيان" — manual-JV line narrative (sprint 4.4). Never set by
    # system-generated entries.
    description = models.CharField(_("description"), max_length=255, blank=True)
    # Sprint 4.4 (3.15.2): schema only — the screen/matching engine is
    # sprint 5.5. Fields live here now so 5.5 doesn't need to migrate
    # every historical JournalLine.
    reconciled_at = models.DateTimeField(_("reconciled at"), null=True, blank=True)
    reconciled_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    bank_statement_line = models.ForeignKey(
        "treasury.BankStatementLine",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="journal_lines",
    )
    # Base-currency amounts (legal_entity.base_currency) — unchanged
    # meaning from before 4.2, still what balance sheets/trial balances
    # read.
    debit = models.DecimalField(max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, default=0)
    credit = models.DecimalField(max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, default=0)
    # Transaction-currency amounts — sprint 4.2 had these implicitly in
    # entry.currency; sprint 5.0 (docs/prompts/sprint-5.md decision 6)
    # moves currency/rate onto the line itself, since a voucher line
    # (5.3) can legitimately differ from its header currency (e.g. a
    # USD invoice settled from a SAR bank). `currency`/`exchange_rate`
    # default to the entry's own at construction time — see
    # build_journal_lines_with_fx_rounding — so every existing caller
    # (invoice posting, manual JVs) is unaffected. debit_fc/credit_fc
    # equal debit/credit whenever currency == base currency (rate 1).
    currency = models.CharField(_("currency"), max_length=3, default="")
    exchange_rate = models.DecimalField(
        _("exchange rate"), max_digits=RATE_MAX_DIGITS, decimal_places=RATE_DECIMAL_PLACES, default=1
    )
    debit_fc = models.DecimalField(
        max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, default=0
    )
    credit_fc = models.DecimalField(
        max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, default=0
    )

    def __str__(self):
        return f"{self.account.code} D{self.debit} C{self.credit}"


class TaxCode(TenantScopedModel):
    """Sprint 4.6 (docs/SYSTEM_ANALYSIS.md 3.16.2; rule 16: "الضريبة على
    البند عبر tax_code (FK) لا نسبة حرّة"). Seeded per country via
    apps/compliance/<country>/tax_codes.json — apps.accounting.services.
    seed_tax_codes_for_country (السعودية أولًا, 3.11)."""

    class Kind(models.TextChoices):
        STANDARD = "standard", _("Standard")
        ZERO_RATED = "zero_rated", _("Zero rated")
        EXEMPT = "exempt", _("Exempt")
        OUT_OF_SCOPE = "out_of_scope", _("Out of scope")
        REVERSE_CHARGE = "reverse_charge", _("Reverse charge")

    class Direction(models.TextChoices):
        OUTPUT = "output", _("Output")
        INPUT = "input", _("Input")
        BOTH = "both", _("Both")

    class Deductible(models.TextChoices):
        FULL = "full", _("Full")
        NONE = "none", _("None")

    code = models.CharField(_("code"), max_length=10)
    name = models.CharField(_("name"), max_length=100)
    rate = models.DecimalField(
        _("rate (%)"), max_digits=PERCENTAGE_MAX_DIGITS, decimal_places=PERCENTAGE_DECIMAL_PLACES, default=0
    )
    kind = models.CharField(_("kind"), max_length=20, choices=Kind.choices)
    direction = models.CharField(_("direction"), max_length=10, choices=Direction.choices)
    deductible = models.CharField(
        _("deductible"), max_length=10, choices=Deductible.choices, default=Deductible.FULL
    )
    # Which GL account output/input tax on this code posts to — usually
    # resolved via a system_key (VAT_OUTPUT/VAT_INPUT/VAT_NON_DEDUCTIBLE)
    # at seed time; nullable because REVERSE_CHARGE posts to two
    # accounts at once (services.build_reverse_charge_tax_specs), not
    # this single FK, and a NONE-deductible code routes its tax amount
    # to the expense/asset account instead (services.
    # resolve_tax_posting_account) — both intentionally not "one account
    # on the code" cases.
    account = models.ForeignKey(
        "accounting.Account", null=True, blank=True, on_delete=models.PROTECT, related_name="tax_codes"
    )
    country_code = models.CharField(_("country code"), max_length=2, default="SA")
    effective_from = models.DateField(_("effective from"), null=True, blank=True)
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="unique_tax_code_per_tenant")
        ]

    def __str__(self):
        return f"{self.code} ({self.rate}%)"


class TaxPeriod(TenantScopedModel):
    """Sprint 4.6 (3.16.2): "مستقل عن الفترة المالية" — the VAT filing
    calendar, independent of FiscalYear/FiscalPeriod (sprint 6). Filing
    itself (status transitions beyond this list) is sprint 10."""

    class PeriodType(models.TextChoices):
        MONTHLY = "monthly", _("Monthly")
        QUARTERLY = "quarterly", _("Quarterly")

    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        FILED = "filed", _("Filed")
        PAID = "paid", _("Paid")

    legal_entity = models.ForeignKey(
        "organization.LegalEntity", on_delete=models.PROTECT, related_name="tax_periods"
    )
    period_type = models.CharField(_("period type"), max_length=10, choices=PeriodType.choices)
    start = models.DateField(_("start"))
    end = models.DateField(_("end"))
    status = models.CharField(_("status"), max_length=10, choices=Status.choices, default=Status.OPEN)
    filed_at = models.DateTimeField(_("filed at"), null=True, blank=True)
    reference = models.CharField(_("reference"), max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "legal_entity", "start", "end"], name="unique_tax_period_range"
            )
        ]

    def __str__(self):
        return f"{self.legal_entity} {self.start}..{self.end}"


class FiscalYear(TenantScopedModel):
    """Sprint 6.1 (3.9, sprint-6.md decision 1/2): one fiscal year per
    tenant (not per legal entity — a branch never has its own fiscal
    year; per-company years are sprint 12), no overlap with another
    year of the same tenant (validated in apps.accounting.periods, not
    a DB constraint — see that module's own note on why)."""

    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        CLOSED = "closed", _("Closed")
        LOCKED = "locked", _("Locked")

    name = models.CharField(_("name"), max_length=50)
    start_date = models.DateField(_("start date"))
    end_date = models.DateField(_("end date"))
    status = models.CharField(_("status"), max_length=10, choices=Status.choices, default=Status.OPEN)
    # decision 2: True for years the daily beat created ahead of time,
    # or the one migration 0025 backfilled for a pre-6.1 tenant — never
    # set on a year a user explicitly created.
    is_auto_created = models.BooleanField(_("auto-created"), default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["start_date"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gt=models.F("start_date")), name="fiscal_year_end_after_start"
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.start_date}..{self.end_date})"


class FiscalPeriod(models.Model):
    """Sprint 6.1 — a child of FiscalYear, same pattern as JournalLine
    under JournalEntry (no direct `tenant` FK; scope every queryset via
    `fiscal_year__tenant`)."""

    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        CLOSED = "closed", _("Closed")
        LOCKED = "locked", _("Locked")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fiscal_year = models.ForeignKey(FiscalYear, on_delete=models.CASCADE, related_name="periods")
    seq = models.PositiveIntegerField(_("sequence"))
    start_date = models.DateField(_("start date"))
    end_date = models.DateField(_("end date"))
    status = models.CharField(_("status"), max_length=10, choices=Status.choices, default=Status.OPEN)
    closed_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    close_note = models.TextField(_("close note"), blank=True)
    # decision 13 (6.7): the full checklist result at the moment of
    # closing, kept for the auditor even if later reopened/re-closed.
    close_snapshot = models.JSONField(null=True, blank=True)
    reopened_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reopened_at = models.DateTimeField(null=True, blank=True)
    reopened_reason = models.TextField(_("reopen reason"), blank=True)
    locked_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    locked_at = models.DateTimeField(null=True, blank=True)
    lock_attestation = models.TextField(_("lock attestation"), blank=True)

    class Meta:
        ordering = ["start_date"]
        constraints = [
            models.UniqueConstraint(fields=["fiscal_year", "seq"], name="unique_fiscal_period_seq"),
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")), name="fiscal_period_end_after_start"
            ),
        ]

    def __str__(self):
        return f"{self.fiscal_year.name} #{self.seq} ({self.start_date}..{self.end_date})"
