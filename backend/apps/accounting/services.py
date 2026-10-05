import json
from collections import OrderedDict
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F, Sum, Window
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.common.formatting import format_money
from apps.numbering.services import next_document_number
from apps.platform.models import AuditLog
from apps.platform.services import log_action

from .models import Account, JournalEntry, JournalLine, TaxCode, TaxPeriod

# Sprint 4.4 (3.15.1): POSTED and REVERSED entries both contribute to
# every balance/report — see DocumentStateMixin's docstring for why
# REVERSED isn't an exclusion. DRAFT/PENDING_APPROVAL/APPROVED never do
# (rule 13: "لا قيد محاسبي يُرحَّل إلا من مستند بحالة POSTED").
REPORTABLE_STATUSES = [JournalEntry.Status.POSTED, JournalEntry.Status.REVERSED]


def unreversed_posted_entries(tenant):
    """Every JournalEntry currently sitting at status=POSTED for this
    tenant — i.e. still open, not yet offset by a reversal. Correct
    for "what's open right now" (e.g. a pre-close checklist); WRONG
    for "how much is this tenant's unresolved debt" (use debt_entries)
    or for a historical gross total (use gross_trial_balance).

    The error this function exists to prevent, made for real on
    2026-10-04: `archive_smoke_tenants` used exactly this definition
    (`status=POSTED`, nothing else) to decide whether a tenant was
    safe to archive, and it refused to archive a tenant that had
    already been used and properly closed (issued, then voided) —
    because the CLOSING reversal entry is itself status=POSTED by
    construction (see reverse_journal_entry below: reversing an entry
    flips the ORIGINAL to REVERSED and creates the reversal as a new
    POSTED row). The command was fixed by switching to debt_entries,
    which excludes the reversal. If you are asking "is there unpaid
    debt" and you reach for this function instead of debt_entries, you
    will reproduce that exact false positive.
    """
    return JournalEntry.objects.filter(tenant=tenant, status=JournalEntry.Status.POSTED)


def debt_entries(tenant):
    """Every JournalEntry that is genuinely unresolved debt: POSTED,
    and not itself a reversal of something else. Use this, not
    unreversed_posted_entries, whenever the question is "how much
    unpaid/unresolved debt does this tenant carry."

    The error this function exists to prevent, made for real on
    2026-10-04: a historical audit of archived tenants used
    `status=POSTED` alone (no further condition) and flagged a
    tenant's own CLOSING reversal entry as if it were 115.00 of fresh
    debt — the entry it reversed had already gone to REVERSED and the
    pair netted to zero, so there was no debt there at all. Any
    reversal entry is ALSO status=POSTED by construction (it is the
    mechanism that closes the original, not more of it), so counting
    it as debt double-counts a position that is already closed.
    Requiring `reverses__isnull=True` excludes exactly that case — if
    you drop that condition and filter on status=POSTED alone, you
    will reproduce that exact miscount.
    """
    return JournalEntry.objects.filter(
        tenant=tenant, status=JournalEntry.Status.POSTED, reverses__isnull=True
    )


def gross_trial_balance(tenant):
    """The historical gross trial balance for this tenant: the sum of
    JournalLine.debit across every entry in REPORTABLE_STATUSES
    (POSTED or REVERSED) — equal to the sum of credit by construction
    (every entry balances). Use this for "what does the gross total
    look like historically", never for a net/current balance (which
    returns to its pre-activity value after a clean reversal — this
    figure does not).

    The error this function exists to prevent, made for real on
    2026-10-04: a restore-vs-live balance comparison was computed with
    `status=POSTED` alone and came out LOWER than the true live
    figure, by exactly the amount of one already-reversed entry — its
    original forward half had flipped to status=REVERSED (reversing
    an entry moves the ORIGINAL to REVERSED and creates a brand-new
    POSTED row for the reversal; see reverse_journal_entry below) and
    silently dropped out of a `status=POSTED`-only sum, while its
    reversal half (still POSTED) stayed in — a half-counted pair, not
    a clean total. REPORTABLE_STATUSES (this module, above) is the
    project's standing answer for which statuses count toward any
    balance/report; filtering on POSTED alone instead will always
    undercount by exactly the gross value of every already-reversed
    entry.
    """
    return (
        JournalLine.objects.filter(entry__tenant=tenant, entry__status__in=REPORTABLE_STATUSES)
        .aggregate(total=Sum("debit"))["total"]
        or Decimal("0")
    )

CHART_TEMPLATES_DIR = Path(__file__).resolve().parent / "chart_templates"
COMPLIANCE_DIR = Path(__file__).resolve().parent.parent / "compliance"

# Fallback codes for a chart that predates sprint 4.3 (system_key didn't
# exist) or otherwise lacks a system_key for something get_system_account
# needs — see get_system_account's docstring. Not used when the tenant's
# chart already has the matching system_key (the normal case for every
# tenant registered from 4.3 onward).
_LEGACY_FALLBACK_CODES = {
    "SALES": "4000",
}

CENTS = Decimal("0.01")
FX_ROUNDING_TOLERANCE = Decimal("0.05")

# CFO_REVIEW_1 C2: system_keys that make an account a "control account"
# by nature (party sub-ledgers and treasury gl_accounts are the other
# two categories, flagged where they're created instead — see
# get_or_create_party_role_account/get_or_create_treasury_account
# below). Kept in sync by hand with apps/accounting/migrations/
# 0018_backfill_control_account_flags.py's own copy (migrations never
# import live app code — see that file's note).
CONTROL_SYSTEM_KEYS = {
    "VAT_OUTPUT", "VAT_INPUT", "VAT_NON_DEDUCTIBLE", "FX_REALIZED", "FX_UNREALIZED",
    "ROUNDING", "OPENING_BALANCE", "RETAINED_EARNINGS",
    # Sprint 5.5 (block 5.5.3): same class as FX_REALIZED/ROUNDING — a
    # system-managed variance account touched only through the cash
    # count -> variance voucher flow, never a free-form manual JV.
    "CASH_COUNT_VARIANCE",
    # Sprint 6.5.0 (decision 2), revised 6.5.6 (decision C, first human
    # UAT): every posting to these three goes through apps.assets.
    # depreciation/disposal (start/addition/disposal), never a
    # free-form manual JV without an override reason. FIXED_ASSETS
    # itself is deliberately NOT here (removed in 6.5.6) — the asset's
    # own purchase, or an addition to it, is an ordinary voucher/manual
    # JV like any other capital expenditure (decision 1); it was never
    # actually posted to by any depreciation/disposal code path, so
    # gating it the same way only blocked the accountant's own normal
    # entry with no corresponding system-code benefit.
    "ACCUM_DEPRECIATION", "DEPRECIATION_EXPENSE", "DISPOSAL_GAIN_LOSS",
    # Sprint 7.0 (D1): inventory's five new system accounts. COGS
    # already existed as a plain (non-control) account on the trading/
    # manufacturing/holding templates — add_missing_system_accounts
    # below flips allow_manual_posting to False on any tenant's
    # existing COGS account too, not just new ones.
    "INVENTORY", "COGS", "INVENTORY_ADJUSTMENT", "GRNI", "GOODS_IN_TRANSIT",
}

# Sprint 7.0.2 (incident #5 follow-up — docs/SYSTEM_ANALYSIS.md §11):
# system_keys an automated posting path (never a human choosing the
# account manually) resolves and posts TO DIRECTLY — as opposed to
# CUSTOMERS/SUPPLIERS/EMPLOYEES/AFFILIATES/BANKS/CUSTODIES/CASH, which
# are only ever used as the PARENT of a per-party/per-instrument
# sub-ledger account real postings actually target (get_or_create_
# party_role_account/get_or_create_treasury_account) — a category
# parent going non-leaf is the designed, safe outcome for those, not a
# risk. Kept in sync by hand with every get_system_account/
# get_required_system_account/_get_system_account_or_fallback call
# site across apps/vouchers, apps/assets, apps/treasury, and this file
# — see apps.accounting.management.commands.check_chart_health, which
# cross-references this set against can_post=False to find a posting
# path a tenant's own chart has silently disabled.
AUTOMATED_POSTING_SYSTEM_KEYS = {
    "VAT_OUTPUT", "VAT_INPUT", "FX_REALIZED", "CASH_COUNT_VARIANCE",
    "ACCUM_DEPRECIATION", "DEPRECIATION_EXPENSE", "FIXED_ASSETS",
    "DISPOSAL_GAIN_LOSS", "SALES",
}

# Sprint 7.0 (D1): the single master spec `add_missing_system_accounts`
# walks — every system_key this project has ever introduced, with the
# one universal code/name/type/parent it uses regardless of
# tenant.business_type (same "one spec, not four" simplification
# migrations 0006/0016/0022/0027 already used for their own one-off
# keys). Idempotent per tenant per key: a tenant that already has the
# key is only touched to fix allow_manual_posting if that key just
# became a CONTROL_SYSTEM_KEYS member (see the command). Replaces the
# old pattern of writing a brand-new one-off data migration every time
# a system account is added — this one command covers every key, past
# and future, for every tenant, forever.
SYSTEM_ACCOUNT_SPECS = [
    {"system_key": "CASH", "code": "1100", "name": "الصناديق", "type": "asset", "parent_code": "1000"},
    {"system_key": "BANKS", "code": "1110", "name": "البنوك", "type": "asset", "parent_code": "1000"},
    {"system_key": "CUSTOMERS", "code": "1200", "name": "العملاء", "type": "asset", "parent_code": "1000"},
    {"system_key": "CUSTODIES", "code": "1300", "name": "عُهد الموظفين", "type": "asset", "parent_code": "1000"},
    {"system_key": "INVENTORY", "code": "1400", "name": "المخزون", "type": "asset", "parent_code": "1000"},
    {
        "system_key": "GOODS_IN_TRANSIT", "code": "1450", "name": "بضاعة بالطريق", "type": "asset",
        "parent_code": "1000",
    },
    {
        "system_key": "AFFILIATES", "code": "1500", "name": "جاري الشركات الشقيقة", "type": "asset",
        "parent_code": "1000",
    },
    {"system_key": "FIXED_ASSETS", "code": "1700", "name": "الأصول الثابتة", "type": "asset", "parent_code": "1000"},
    {
        "system_key": "ACCUM_DEPRECIATION", "code": "1750", "name": "مجمع إهلاك الأصول الثابتة", "type": "asset",
        "parent_code": "1000",
    },
    {"system_key": "SUPPLIERS", "code": "2100", "name": "الموردون", "type": "liability", "parent_code": "2000"},
    {
        "system_key": "GRNI", "code": "2120", "name": "بضاعة مستلمة لم تُفوتر (GRNI)", "type": "liability",
        "parent_code": "2000",
    },
    {
        "system_key": "EMPLOYEES", "code": "2150", "name": "رواتب الموظفين المستحقة", "type": "liability",
        "parent_code": "2000",
    },
    {"system_key": "VAT_OUTPUT", "code": "2200", "name": "ضريبة المخرجات", "type": "liability", "parent_code": "2000"},
    {"system_key": "VAT_INPUT", "code": "2300", "name": "ضريبة المدخلات", "type": "liability", "parent_code": "2000"},
    {
        "system_key": "VAT_NON_DEDUCTIBLE", "code": "2350", "name": "ضريبة غير قابلة للخصم", "type": "liability",
        "parent_code": "2000",
    },
    {
        "system_key": "RETAINED_EARNINGS", "code": "3200", "name": "الأرباح المرحّلة", "type": "equity",
        "parent_code": "3000",
    },
    {
        "system_key": "OPENING_BALANCE", "code": "3900", "name": "الأرصدة الافتتاحية", "type": "equity",
        "parent_code": "3000",
    },
    {"system_key": "SALES", "code": "4100", "name": "إيرادات المبيعات", "type": "revenue", "parent_code": "4000"},
    {
        "system_key": "DISPOSAL_GAIN_LOSS", "code": "4900", "name": "أرباح/خسائر استبعاد الأصول", "type": "revenue",
        "parent_code": "4000",
    },
    {"system_key": "COGS", "code": "5050", "name": "تكلفة البضاعة المباعة", "type": "expense", "parent_code": "5000"},
    {
        "system_key": "INVENTORY_ADJUSTMENT", "code": "5070", "name": "فروق وتسويات المخزون", "type": "expense",
        "parent_code": "5000",
    },
    {
        "system_key": "DEPRECIATION_EXPENSE", "code": "5150", "name": "مصروف إهلاك الأصول الثابتة", "type": "expense",
        "parent_code": "5000",
    },
    {"system_key": "ROUNDING", "code": "5900", "name": "فروق تقريب العملة", "type": "expense", "parent_code": "5000"},
    {"system_key": "FX_REALIZED", "code": "5910", "name": "فروق عملة محققة", "type": "expense", "parent_code": "5000"},
    {
        "system_key": "FX_UNREALIZED", "code": "5920", "name": "فروق عملة غير محققة", "type": "expense",
        "parent_code": "5000",
    },
    {
        "system_key": "CASH_COUNT_VARIANCE", "code": "5930", "name": "فروق جرد الصندوق", "type": "expense",
        "parent_code": "5000",
    },
]

# Sprint 3.3/3.4: which system_key parent a given PartyRole.Role's
# sub-ledger account is created under. Deliberately excludes BANK (a
# PartyRole choice that's currently unused going forward — treasury.Bank
# is its own model, see the Decision Log) from ever creating an Account.
_SYSTEM_KEY_BY_PARTY_ROLE = {
    "customer": "CUSTOMERS",
    "supplier": "SUPPLIERS",
    "employee": "EMPLOYEES",
    "affiliate": "AFFILIATES",
}


def _load_chart_template(business_type):
    path = CHART_TEMPLATES_DIR / f"{business_type}.json"
    if not path.exists():
        path = CHART_TEMPLATES_DIR / "service.json"
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _create_account_tree(tenant, nodes, parent=None):
    for node in nodes:
        children = node.get("children") or []
        account = Account.objects.create(
            tenant=tenant,
            parent=parent,
            code=node["code"],
            name=node["name"],
            type=node["type"],
            system_key=node.get("system_key", ""),
            is_intercompany=node.get("is_intercompany", False),
            allow_posting=not children,
            allow_manual_posting=node.get("system_key", "") not in CONTROL_SYSTEM_KEYS,
            is_system=True,
        )
        if children:
            _create_account_tree(tenant, children, parent=account)


def seed_chart_of_accounts(tenant):
    """Create the chart of accounts for a brand-new tenant, from the
    activity-based template matching tenant.business_type (sprint 4.3,
    3.4: "قوالب دليل حسب النشاط ... تُطبَّق عند التسجيل بدل دليل واحد
    للجميع"). Every template lives in apps/accounting/chart_templates/
    as JSON, tagging the accounts other code looks up by meaning
    (system_key) rather than by hardcoded number — see
    get_system_account.
    """
    template = _load_chart_template(tenant.business_type)
    _create_account_tree(tenant, template)


def get_system_account(tenant, system_key):
    """The account tagged with this system_key in the tenant's chart —
    None if the chart has none (e.g. a very old chart from before 4.3
    whose migration backfill didn't map that particular key; callers
    that can't function without one should fall back to
    _LEGACY_FALLBACK_CODES or raise a clear error, not silently post to
    the wrong account)."""
    return Account.objects.filter(tenant=tenant, system_key=system_key).first()


def get_required_system_account(tenant, system_key):
    """Sprint 7.0.1 (rule-11 incident #4 — docs/SYSTEM_ANALYSIS.md
    §11): the strict counterpart get_system_account's own docstring
    above already calls for — raises, naming the missing key, instead
    of returning None. Every POSTING path that cannot correctly
    continue without a specific system account (the inventory engine
    from block 7.3 onward: INVENTORY/COGS/INVENTORY_ADJUSTMENT/GRNI/
    GOODS_IN_TRANSIT) must call this, never get_system_account
    directly — a posting operation is rejected outright if the account
    is missing, never silently redirected to a different account.

    Deliberately NOT applied to get_or_create_party_role_account/
    get_or_create_treasury_account above: those are documented,
    pre-existing "return None, not an error" convenience-account
    auto-creation on a party-role/bank/cash-box/custody change, not a
    posting operation — changing their behavior now would be an
    unrelated, unrequested change to tenants already relying on it
    today (confirmed live: 12 tenants with a pre-4.3 chart)."""
    account = get_system_account(tenant, system_key)
    if account is None:
        raise ValidationError(
            _("Required system account '%(key)s' is missing for this tenant.") % {"key": system_key}
        )
    return account


def _get_system_account_or_fallback(tenant, system_key):
    account = get_system_account(tenant, system_key)
    if account is not None:
        return account
    fallback_code = _LEGACY_FALLBACK_CODES.get(system_key)
    if fallback_code:
        account = Account.objects.filter(tenant=tenant, code=fallback_code).first()
    if account is None:
        raise ValidationError(
            _("لا يوجد حساب في الدليل بمفتاح %(key)s — راجع دليل الحسابات.") % {"key": system_key}
        )
    return account


def seed_tax_codes_for_country(tenant, country_code):
    """Sprint 4.6 (3.11/3.16.2): "حزمة الامتثال كقابلة للتوصيل لكل
    دولة (ZATCA أولًا)" — apps/compliance/<country>/tax_codes.json.
    Idempotent (get_or_create per code) so it's safe to call again for
    a tenant that already has some/all of the codes. Silently does
    nothing for a country with no compliance package yet."""
    path = COMPLIANCE_DIR / country_code.lower() / "tax_codes.json"
    if not path.exists():
        return
    with path.open(encoding="utf-8") as f:
        codes = json.load(f)
    for entry in codes:
        account = get_system_account(tenant, entry["system_key"]) if entry.get("system_key") else None
        TaxCode.objects.get_or_create(
            tenant=tenant,
            code=entry["code"],
            defaults={
                "name": entry["name"],
                "rate": entry["rate"],
                "kind": entry["kind"],
                "direction": entry["direction"],
                "deductible": entry["deductible"],
                "account": account,
                "country_code": country_code,
            },
        )


def resolve_tax_posting_account(tenant, tax_code):
    """Which account a tax_code's amount posts to. None for a
    NONE-deductible code (sprint 4.6: "NONE deductible يُحمَّل على حساب
    المصروف/الأصل لا حساب الضريبة") — the caller (a purchase-invoice
    flow, sprint 8) must route that amount onto the expense/asset
    account itself instead; nothing in this sprint calls this with a
    NONE-deductible code for real yet, since sales-side output tax is
    always fully deductible/reportable by definition."""
    if tax_code.deductible == TaxCode.Deductible.NONE:
        return None
    if tax_code.account_id:
        return tax_code.account
    return get_system_account(tenant, "VAT_OUTPUT" if tax_code.direction != "input" else "VAT_INPUT")


def build_reverse_charge_tax_specs(tenant, tax_code, base_amount, cost_center=None):
    """Sprint 4.6: REVERSE_CHARGE self-assesses both sides of the VAT at
    once — "يولّد قيدًا ضريبيًا مزدوجًا (مخرجات + مدخلات)". Returns two
    line_specs (output credit + input debit, equal amounts, net zero
    cash effect) for the caller to include alongside its other lines.
    Not exercised by any real document flow until the supplier-invoice
    screen (sprint 8); the logic is ready and unit-tested now."""
    if base_amount == 0:
        return []
    output_account = get_system_account(tenant, "VAT_OUTPUT")
    input_account = get_system_account(tenant, "VAT_INPUT")
    return [
        {"account": output_account, "cost_center": cost_center, "debit_fc": Decimal("0"), "credit_fc": base_amount},
        {"account": input_account, "cost_center": cost_center, "debit_fc": base_amount, "credit_fc": Decimal("0")},
    ]


def generate_tax_periods_for_year(legal_entity, year):
    """Sprint 4.6 (3.16.2): "توليد تلقائي للسنة الحالية حسب نوع الفترة
    المختار في إعدادات الكيان" — idempotent (get_or_create per range).
    Calendar-year monthly/quarterly periods; the filing itself is
    sprint 10."""
    import calendar
    from datetime import date

    periods = []
    if legal_entity.tax_period_type == "quarterly":
        ranges = [(1, 3), (4, 6), (7, 9), (10, 12)]
    else:
        ranges = [(m, m) for m in range(1, 13)]

    for start_month, end_month in ranges:
        start = date(year, start_month, 1)
        end = date(year, end_month, calendar.monthrange(year, end_month)[1])
        period, _created = TaxPeriod.objects.get_or_create(
            tenant=legal_entity.tenant,
            legal_entity=legal_entity,
            start=start,
            end=end,
            defaults={"period_type": legal_entity.tax_period_type},
        )
        periods.append(period)
    return periods


def get_or_create_party_role_account(party, role):
    """Sprint 4.3 (3.4): the sub-ledger/running account for one
    (party, role) pair, auto-created the first time that role is
    created for this party — idempotent (re-checks for an existing
    account first, never creates a duplicate). A party holding two
    roles (e.g. customer + supplier) ends up with two Account rows,
    both with `party` set to it, one under CUSTOMERS and one under
    SUPPLIERS — "الطرف بدورين = حسابان (عملاء/موردين)".

    Returns None (not an error) if the tenant's chart has no parent for
    this role's system_key — an old/custom chart without it simply
    doesn't get sub-ledger automation; the party itself is unaffected.
    """
    system_key = _SYSTEM_KEY_BY_PARTY_ROLE.get(role)
    if system_key is None:
        return None
    existing = Account.objects.filter(
        tenant=party.tenant_id, party=party, parent__system_key=system_key
    ).first()
    if existing is not None:
        return existing
    parent = get_system_account(party.tenant, system_key)
    if parent is None:
        return None
    next_seq = parent.children.count() + 1
    return Account.objects.create(
        tenant=party.tenant,
        parent=parent,
        code=f"{parent.code}.{next_seq:03d}",
        name=party.name,
        type=parent.type,
        allow_posting=True,
        allow_manual_posting=False,
        is_system=False,
        party=party,
    )


def get_or_create_treasury_account(instance, system_key):
    """Same idea as get_or_create_party_role_account but for
    Bank/CashBox/Custody, which already carry their own `gl_account` FK
    (sprint 3, "designed nullable-for-now") instead of needing a
    party-style lookup — ARCH_REVIEW_1.md debt #20."""
    if instance.gl_account_id:
        return instance.gl_account
    parent = get_system_account(instance.tenant, system_key)
    if parent is None:
        return None
    next_seq = parent.children.count() + 1
    account = Account.objects.create(
        tenant=instance.tenant,
        parent=parent,
        code=f"{parent.code}.{next_seq:03d}",
        name=instance.name,
        type=parent.type,
        allow_posting=True,
        allow_manual_posting=False,
        is_system=False,
    )
    instance.gl_account = account
    instance.save(update_fields=["gl_account"])
    return account


def check_cost_center_required(tenant, account, cost_center):
    """Sprint 6.8 (D5, decision 19): TenantFeatures.cost_center_required
    — off by default, no effect on any other tenant. Checked at each
    input-validation point that takes a free-form account choice
    (manual JV lines, voucher direct account lines) — never inside the
    shared posting machinery (build_journal_lines_with_fx_rounding),
    since invoice lines resolve their account later, at posting time,
    from a value already validated at invoice-creation time instead."""
    if cost_center is not None or account.type not in (Account.Type.REVENUE, Account.Type.EXPENSE):
        return
    # TenantFeatures is only ever created by RegisterSerializer — a
    # tenant built any other way (TenantFactory in tests, an old script)
    # legitimately has none yet; treat that the same as "not enabled"
    # rather than crashing every posting path.
    features = getattr(tenant, "features", None)
    if features is None or not features.cost_center_required:
        return
    raise ValidationError(
        _("سطر على حساب إيراد أو مصروف (%(code)s) يتطلب مركز تكلفة.") % {"code": account.code}
    )


def build_journal_lines_with_fx_rounding(tenant, entry, line_specs, exchange_rate):
    """Sprint 4.2 (3.15.3), extended in 4.3 with the posting guard (3.4:
    "لا ترحيل على حساب له أبناء") and JournalLine.party auto-fill (3.4:
    "auto-filled when posting to a sub-ledger account"); extended again
    in 5.0 (docs/prompts/sprint-5.md decision 6) with per-line
    currency/rate instead of assuming every line shares entry.currency.

    Converts each line_spec into an unsaved JournalLine with debit/
    credit (legal_entity.base_currency) also populated — each line
    rounded to the cent independently (ROUND_HALF_UP), same as every
    other money computation in this project. Each spec is one of:
      - {"account", "cost_center"?, "debit_fc", "credit_fc",
         "currency"?, "exchange_rate"?} — the ordinary case. `currency`/
        `exchange_rate` default to the entry's own (unchanged behavior
        for every sprint-4 caller); debit/credit = fc × rate.
      - {"account", ..., "debit_base"/"credit_base", "currency"?,
         "exchange_rate"?} — **system code only, never exposed on any
         API input serializer**: the base-currency amount is given
         directly (e.g. sprint 5.3's invoice allocation, which must use
         the invoice's own historical rate, not today's). debit_fc/
         credit_fc are then back-derived from the given rate for
         display consistency; if no rate is supplied the fc columns
         mirror the base amount 1:1 (rate 1), since a base-only line
         has no other currency of its own to report.

    Converting each line separately can leave the base-currency debit
    and credit totals off by a few cents even though the fc totals are
    exactly balanced (rounding is not linear) — "التوازن إلزامي
    بالعملتين ... وفرق التقريب (≤ 0.05) يُضاف لسطر تقريب تلقائي". A gap
    bigger than that tolerance means a real bug upstream, not rounding
    noise, so it raises instead of silently absorbing it.
    """
    lines = []
    for spec in line_specs:
        account = spec["account"]
        if not account.can_post:
            raise ValidationError(
                _(
                    "لا يمكن الترحيل على الحساب %(code)s: إما أنه حساب أب له فروع "
                    "أو أن الترحيل عليه معطّل."
                )
                % {"code": account.code}
            )
        line_currency = spec.get("currency") or entry.currency
        line_rate = spec.get("exchange_rate", exchange_rate)

        if "debit_base" in spec or "credit_base" in spec:
            debit_base = spec.get("debit_base", Decimal("0"))
            credit_base = spec.get("credit_base", Decimal("0"))
            debit_fc = spec.get("debit_fc", debit_base if line_rate == 1 else debit_base / line_rate)
            credit_fc = spec.get("credit_fc", credit_base if line_rate == 1 else credit_base / line_rate)
        else:
            debit_fc = spec["debit_fc"]
            credit_fc = spec["credit_fc"]
            debit_base = (debit_fc * line_rate).quantize(CENTS, rounding=ROUND_HALF_UP)
            credit_base = (credit_fc * line_rate).quantize(CENTS, rounding=ROUND_HALF_UP)

        lines.append(
            JournalLine(
                entry=entry,
                account=account,
                cost_center=spec.get("cost_center"),
                party=account.party,
                description=spec.get("description", ""),
                currency=line_currency,
                exchange_rate=line_rate,
                debit_fc=debit_fc,
                credit_fc=credit_fc,
                debit=debit_base,
                credit=credit_base,
            )
        )

    debit_total = sum((line.debit for line in lines), Decimal("0"))
    credit_total = sum((line.credit for line in lines), Decimal("0"))
    diff = credit_total - debit_total
    if diff != 0:
        if abs(diff) > FX_ROUNDING_TOLERANCE:
            raise ValueError(
                f"FX conversion rounding gap {diff} exceeds the {FX_ROUNDING_TOLERANCE} "
                "tolerance — this indicates a real bug upstream, not rounding noise."
            )
        rounding_account = _get_system_account_or_fallback(tenant, "ROUNDING")
        base_currency = entry.legal_entity.base_currency
        if diff > 0:
            lines.append(
                JournalLine(
                    entry=entry, account=rounding_account, currency=base_currency,
                    debit=diff, credit=Decimal("0"), debit_fc=diff,
                )
            )
        else:
            lines.append(
                JournalLine(
                    entry=entry, account=rounding_account, currency=base_currency,
                    debit=Decimal("0"), credit=-diff, credit_fc=-diff,
                )
            )
    return lines


def _tax_line_specs(tenant, invoice):
    """Sprint 4.6 (3.16.2): one tax line per distinct TaxCode used on
    the invoice (grouped, summed), not one lump VAT line — "سطر ضريبة
    لكل TaxCode في الفاتورة على حسابه". Lines whose tax_code computed
    to zero tax (Z/E/O) contribute no line at all — posting a
    zero-amount line is meaningless. A REVERSE_CHARGE code posts its
    dual output+input lines instead of a single credit."""
    groups = OrderedDict()
    for line in invoice.lines.select_related("tax_code").order_by("tax_code_id"):
        if line.line_tax == 0:
            continue
        key = line.tax_code_id
        if key not in groups:
            groups[key] = {"tax_code": line.tax_code, "amount": Decimal("0")}
        groups[key]["amount"] += line.line_tax

    specs = []
    for group in groups.values():
        tax_code, amount = group["tax_code"], group["amount"]
        if tax_code.kind == TaxCode.Kind.REVERSE_CHARGE:
            specs.extend(build_reverse_charge_tax_specs(tenant, tax_code, amount))
            continue
        account = resolve_tax_posting_account(tenant, tax_code)
        if account is not None:
            specs.append({"account": account, "debit_fc": Decimal("0"), "credit_fc": amount})
    return specs


def _cost_center_revenue_specs(invoice, revenue_account):
    """Sprint 4.4 (ARCH_REVIEW_1.md debt #5, resolved): one revenue
    line per distinct cost_center among the invoice's lines (grouped,
    summed) instead of one aggregated line — "فاتورة ببندين على
    مركزين تولّد سطري إيراد". Lines with no cost_center are grouped
    together under a single None-cost_center line."""
    groups = OrderedDict()
    for line in invoice.lines.select_related("cost_center").order_by("cost_center_id"):
        key = line.cost_center_id
        if key not in groups:
            groups[key] = {"cost_center": line.cost_center, "amount": Decimal("0")}
        groups[key]["amount"] += line.line_subtotal
    return [
        {
            "account": revenue_account,
            "cost_center": group["cost_center"],
            "debit_fc": Decimal("0"),
            "credit_fc": group["amount"],
        }
        for group in groups.values()
    ]


@transaction.atomic
def post_invoice_journal_entry(invoice):
    """Post a balanced journal entry for an issued invoice — created
    directly at status=POSTED (sprint 4.4, 3.15.1): this is a
    system-generated entry, not a manual JV, so it isn't subject to the
    draft/approval workflow — the invoice's own issue() action is
    already the human decision point.

    Debits the customer's own sub-ledger account (auto-created under
    CUSTOMERS, sprint 4.3 — not a shared lump "Accounts Receivable"
    bucket, so per-customer statements/aging can read JournalLine.party
    directly) for the invoice total, credits Sales Revenue (split one
    line per cost center, sprint 4.4) for the subtotal and Tax Payable
    for the tax — always balanced by construction since credit total ==
    debit total (in invoice.currency; build_journal_lines_with_fx_rounding
    handles the base-currency conversion and rounding, sprint 4.2).
    """
    tenant = invoice.tenant
    from apps.parties.models import PartyRole
    from apps.sales.models import Invoice

    from .periods import assert_open_period

    assert_open_period(tenant, invoice.issue_date)

    ar = get_or_create_party_role_account(invoice.party, PartyRole.Role.CUSTOMER)
    if ar is None:
        ar = _get_system_account_or_fallback(tenant, "CUSTOMERS")
    revenue = _get_system_account_or_fallback(tenant, "SALES")

    entry = JournalEntry.objects.create(
        tenant=tenant,
        legal_entity=invoice.legal_entity,
        date=invoice.issue_date,
        memo=f"فاتورة {invoice.number}",
        number=next_document_number(tenant, "journal_entry", invoice.legal_entity, invoice.issue_date),
        status=JournalEntry.Status.POSTED,
        source_type="invoice",
        source_id=invoice.id,
        content_type=ContentType.objects.get_for_model(Invoice),
        object_id=invoice.id,
        currency=invoice.currency,
        exchange_rate=invoice.exchange_rate,
    )

    line_specs = [
        {"account": ar, "debit_fc": invoice.total, "credit_fc": Decimal("0")},
        *_cost_center_revenue_specs(invoice, revenue),
    ]
    line_specs.extend(_tax_line_specs(tenant, invoice))

    lines = build_journal_lines_with_fx_rounding(tenant, entry, line_specs, invoice.exchange_rate)
    JournalLine.objects.bulk_create(lines)
    return entry


@transaction.atomic
def void_invoice_journal_entry(invoice):
    """Post a reversing journal entry for a voided (cancelled) invoice —
    docs/SYSTEM_ANALYSIS.md section 4 rule 4: every journal entry stays
    balanced, so voiding never edits or deletes the original entry, it
    posts a mirror-image entry (debit <-> credit swapped per line, same
    accounts and cost centers) that nets it to zero.

    Sprint 4.4: the original flips to REVERSED (a terminal marker, not
    an exclusion — see DocumentStateMixin/REPORTABLE_STATUSES) and the
    new entry is created directly at POSTED, linked back via `reverses`.
    """
    original = JournalEntry.objects.get(
        tenant=invoice.tenant, source_type="invoice", source_id=invoice.id
    )
    # Same exception as reverse_journal_entry: gated on today's date,
    # not the original invoice's (often-closed) issue_date.
    from .periods import assert_open_period

    assert_open_period(invoice.tenant, timezone.localdate())
    reversal = JournalEntry.objects.create(
        tenant=invoice.tenant,
        legal_entity=invoice.legal_entity,
        date=timezone.localdate(),
        memo=f"إلغاء فاتورة {invoice.number}",
        number=next_document_number(
            invoice.tenant, "journal_entry", invoice.legal_entity, timezone.localdate()
        ),
        status=JournalEntry.Status.POSTED,
        reverses=original,
        source_type="invoice_void",
        source_id=invoice.id,
        content_type=original.content_type,
        object_id=original.object_id,
        currency=original.currency,
        exchange_rate=original.exchange_rate,
    )
    JournalLine.objects.bulk_create(
        [
            JournalLine(
                entry=reversal,
                account=line.account,
                cost_center=line.cost_center,
                party=line.party,
                currency=line.currency,
                exchange_rate=line.exchange_rate,
                debit_fc=line.credit_fc,
                credit_fc=line.debit_fc,
                debit=line.credit,
                credit=line.debit,
            )
            for line in original.lines.all()
        ]
    )
    original.status = JournalEntry.Status.REVERSED
    original.save(update_fields=["status"])
    return reversal


# ---------------------------------------------------------------------
# Sprint 4.4: manual journal entries — "القيود اليدوية" screen. Unlike
# post_invoice_journal_entry (system-generated, straight to POSTED),
# these start at DRAFT and move through the unified status machine
# (DocumentStateMixin) one explicit action at a time.
# ---------------------------------------------------------------------


@transaction.atomic
def create_manual_journal_entry(
    tenant, user, legal_entity, date, line_specs, currency=None, exchange_rate=None, memo="", reference="",
    override_reason="", request=None,
):
    """CFO_REVIEW_1 C2: any line targeting a control account
    (`Account.allow_manual_posting=False`) requires `override_reason`
    — the caller (the view) has already checked the user holds
    `accounting.post_control_accounts` before getting here; this
    function just does the actual gating + logging + flagging, so a
    future second caller of this service can't bypass either check by
    skipping the view."""
    from .periods import assert_open_period

    assert_open_period(tenant, date)

    for spec in line_specs:
        check_cost_center_required(tenant, spec["account"], spec.get("cost_center"))

    control_lines = [spec for spec in line_specs if not spec["account"].allow_manual_posting]
    if control_lines:
        if not override_reason:
            raise ValidationError(
                _(
                    "لا يمكن الترحيل يدويًا على حساب رقابة (%(codes)s) بدون تجاوز مسجَّل بسبب — "
                    "استخدم سند قبض/صرف أو حرّك الضريبة من الفاتورة."
                )
                % {"codes": ", ".join(sorted({spec["account"].code for spec in control_lines}))}
            )
        from apps.access.services import user_has_permission

        if not user_has_permission(user, "accounting.post_control_accounts"):
            raise PermissionDenied(
                _("You do not have permission to override a control account's posting restriction.")
            )

    currency = currency or legal_entity.base_currency
    exchange_rate = exchange_rate if exchange_rate is not None else Decimal("1")
    entry = JournalEntry.objects.create(
        tenant=tenant,
        legal_entity=legal_entity,
        date=date,
        memo=memo,
        reference=reference,
        number=next_document_number(tenant, "journal_entry", legal_entity, date),
        status=JournalEntry.Status.DRAFT,
        created_by=user,
        currency=currency,
        exchange_rate=exchange_rate,
        is_control_override=bool(control_lines),
    )
    lines = build_journal_lines_with_fx_rounding(tenant, entry, line_specs, exchange_rate)
    _require_fc_balance_if_single_currency(entry, lines)
    JournalLine.objects.bulk_create(lines)
    if control_lines:
        log_action(
            actor_type=AuditLog.ActorType.TENANT_USER, actor_id=user.id,
            action="journal_entry.control_account_override", target_type="journal_entry", target_id=entry.id,
            tenant_id=tenant.id,
            after={"reason": override_reason, "accounts": sorted({spec["account"].code for spec in control_lines})},
            request=request,
        )
    return entry


def replace_manual_journal_entry_lines(entry, user, line_specs, override_reason="", request=None):
    """Sprint 6.6.5 (§6.2 addition): generalizes the exact full-replace
    pattern apps.accounting.opening_balances.replace_opening_balance_
    lines built for OpeningBalanceEntry in 6.6.3d — a still-DRAFT
    manual entry's own page can re-save its whole line set on every
    edit, same validation as create_manual_journal_entry (control-
    account override, cost-center requirement, FX-rounding, balance),
    just never touching date/currency/exchange_rate/memo/reference.
    An auto-generated entry (source_type set) never reaches DRAFT in
    the first place (see JournalEntryViewSet's own docstring), so
    there's no separate guard needed for that case here."""
    if entry.status != JournalEntry.Status.DRAFT:
        raise ValidationError(_("لا يمكن تعديل سطور قيد إلا وهو في حالة مسودة."))

    for spec in line_specs:
        check_cost_center_required(entry.tenant, spec["account"], spec.get("cost_center"))

    control_lines = [spec for spec in line_specs if not spec["account"].allow_manual_posting]
    if control_lines:
        if not override_reason:
            raise ValidationError(
                _(
                    "لا يمكن الترحيل يدويًا على حساب رقابة (%(codes)s) بدون تجاوز مسجَّل بسبب — "
                    "استخدم سند قبض/صرف أو حرّك الضريبة من الفاتورة."
                )
                % {"codes": ", ".join(sorted({spec["account"].code for spec in control_lines}))}
            )
        from apps.access.services import user_has_permission

        if not user_has_permission(user, "accounting.post_control_accounts"):
            raise PermissionDenied(
                _("You do not have permission to override a control account's posting restriction.")
            )

    lines = build_journal_lines_with_fx_rounding(entry.tenant, entry, line_specs, entry.exchange_rate)
    _require_fc_balance_if_single_currency(entry, lines)
    entry.lines.all().delete()
    JournalLine.objects.bulk_create(lines)
    if bool(control_lines) != entry.is_control_override:
        entry.is_control_override = bool(control_lines)
        entry.save(update_fields=["is_control_override"])
    return entry


def _require_fc_balance_if_single_currency(entry, lines):
    """Sprint 5.0 (docs/prompts/sprint-5.md decision 6): "التوازن
    بالعملة الأساسية إلزامي دائمًا؛ التوازن بعملة المعاملة يُفرض على
    القيود اليدوية أحادية العملة فقط." Once a manual JV can carry
    mixed-currency lines (a capability this sprint adds the plumbing
    for, exercised for real by vouchers in 5.3) there is no single
    transaction currency to balance by, so the check only applies when
    every line — including any auto-appended rounding line — still
    shares the entry's own currency (true for every sprint-4-era
    manual JV, which is exactly the behavior this must not change).
    """
    if not all(line.currency == entry.currency for line in lines):
        return
    debit_fc_total = sum((line.debit_fc for line in lines), Decimal("0"))
    credit_fc_total = sum((line.credit_fc for line in lines), Decimal("0"))
    if debit_fc_total != credit_fc_total:
        raise ValidationError(
            _("القيد غير متوازن بعملة المعاملة: إجمالي المدين %(debit)s لا يساوي إجمالي الدائن %(credit)s.")
            % {"debit": format_money(debit_fc_total), "credit": format_money(credit_fc_total)}
        )


def _transition_journal_entry(entry, new_status, user, action):
    old_status = entry.status
    entry.status = new_status
    entry.save(update_fields=["status"])
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER,
        actor_id=user.id,
        action=f"journal_entry.{action}",
        target_type="journal_entry",
        target_id=entry.id,
        tenant_id=entry.tenant_id,
        before={"status": old_status},
        after={"status": new_status},
    )


def _journal_entry_amount_base(entry):
    return entry.lines.aggregate(total=Sum("debit"))["total"] or Decimal("0")


def submit_journal_entry_for_approval(entry, user, request=None):
    """Sprint 4.5: delegates to the generic apps.approvals engine —
    3.15.9's "لا قيد يدوي يُرحَّل بلا اعتماد" is now enforced by a real,
    tenant-editable ApprovalRule (seeded by default at registration and
    backfilled for existing tenants, min_amount=0 -> Owner) instead of
    the hardcoded check 4.4 shipped with."""
    from apps.approvals.services import submit_for_approval

    submit_for_approval(entry, user, "journal_entry", _journal_entry_amount_base(entry), request=request)
    return entry


def approve_journal_entry(entry, user, request=None, emergency_reason=""):
    from apps.approvals.services import approve as approvals_approve

    approvals_approve(
        entry, user, "journal_entry", _journal_entry_amount_base(entry), request=request,
        emergency_reason=emergency_reason,
    )
    return entry


def reject_journal_entry(entry, user, reason, request=None):
    from apps.approvals.services import reject as approvals_reject

    approvals_reject(entry, user, "journal_entry", reason, request=request)
    return entry


def withdraw_journal_entry(entry, user, request=None):
    """CFO_REVIEW_1 C3."""
    from apps.approvals.services import withdraw as approvals_withdraw

    approvals_withdraw(entry, user, "journal_entry", request=request)
    return entry


@transaction.atomic
def post_journal_entry(entry, user, request=None):
    """CFO_REVIEW_1 C4: locks the row before re-checking its status, so
    two concurrent "post" requests for the same entry can't both pass
    the precondition check — the second blocks on the lock, then finds
    the row already POSTED and raises cleanly instead of double-posting.
    Syncs `entry.status` in place (same object identity, same pattern
    as apps.approvals.services._lock) rather than rebinding to a new
    instance — every existing caller keeps working whether or not it
    captures this function's return value."""
    entry.status = JournalEntry.objects.select_for_update().get(pk=entry.pk).status
    if entry.status != JournalEntry.Status.APPROVED:
        raise ValidationError(_("Only an approved entry can be posted."))
    from .periods import assert_open_period

    assert_open_period(entry.tenant, entry.date)
    _transition_journal_entry(entry, JournalEntry.Status.POSTED, user, "post")
    return entry


class OpeningEntryReversalRejected(Exception):
    """Sprint 6.3 (decision 8): "reverse_journal_entry يرفض is_opening
    (409)" — the view maps this to 409, distinct from the ordinary 400
    an unreversable-for-other-reasons entry gets. An opening balance's
    only correction path is a new ADJUSTMENT document (apps.accounting.
    opening_balances), never a reversal of the posted entry itself."""


class StockDocumentReversalRejected(Exception):
    """Sprint 7.2.6 (D5 spec, task 5): "reverse_journal_entry على قيد
    مخزني مباشرةً -> 409 «التصحيح بمستند معاكس»" — built now even
    though no caller creates a stock-sourced JournalEntry yet (7.3's
    engine is what will set content_type/object_id to a StockDocument
    when it posts one), same "guard before its real caller exists"
    shape as 7.2.5's own is_batch_expired. Checked via content_type,
    the project's own current standard for "what created this entry"
    (JournalEntry's own docstring: source_type/source_id are the
    superseded, pre-GenericFK mechanism — recurring/is_opening still
    read the old field above only because they predate this)."""


class DepreciationEntryReversalRejected(Exception):
    """Sprint 6.5 (decision 12): same "not reversed individually, only
    corrected forward" rule as OpeningEntryReversalRejected — a
    depreciation installment's own JournalEntry is corrected by a new
    addition or disposal schedule (apps.assets.depreciation), never by
    reversing the installment itself. Defense-in-depth: the primary
    path is apps.accounting.views.JournalEntryViewSet.reverse's own
    up-front check, mirroring is_opening's dual layering there."""


@transaction.atomic
def reverse_journal_entry(entry, user, reason, date=None):
    """CFO_REVIEW_1 C8: `date` defaults to today and may never precede
    the original entry's own date (a reversal can't happen before what
    it reverses). CFO_REVIEW_1 C4: row-locked (in place — see
    post_journal_entry's docstring) before the status check."""
    entry.status = JournalEntry.objects.select_for_update().get(pk=entry.pk).status
    if entry.status != JournalEntry.Status.POSTED:
        raise ValidationError(_("Only a posted entry can be reversed."))
    if entry.content_type is not None and entry.content_type.model == "stockdocument":
        raise StockDocumentReversalRejected(
            str(_("A stock-document-sourced entry is reversed via its own document, not reversed directly."))
        )
    if entry.is_opening:
        raise OpeningEntryReversalRejected(
            str(_("A posted opening balance entry can never be reversed — correct it with a new adjustment instead."))
        )
    if entry.source_type == "recurring":
        from .models import RecurringEntry

        if RecurringEntry.objects.filter(id=entry.source_id, kind=RecurringEntry.Kind.DEPRECIATION).exists():
            raise DepreciationEntryReversalRejected(
                str(_("قيد قسط الإهلاك لا يُعكس فرديًا — التصحيح بإضافة إلى الأصل أو استبعاده فقط."))
            )
    if not reason:
        raise ValidationError(_("A reason is required to reverse a journal entry."))
    reversal_date = date or timezone.localdate()
    if reversal_date < entry.date:
        raise ValidationError(_("The reversal date cannot precede the original entry's date."))

    tenant = entry.tenant
    # Decision 3's own exception: the reversal is gated on ITS OWN
    # date's period being open, never the original entry's (which may
    # be — is often expected to be — closed by now).
    from .periods import assert_open_period

    assert_open_period(tenant, reversal_date)
    reversal = JournalEntry.objects.create(
        tenant=tenant,
        legal_entity=entry.legal_entity,
        date=reversal_date,
        memo=f"عكس قيد {entry.number or entry.id}: {reason}",
        number=next_document_number(tenant, "journal_entry", entry.legal_entity, reversal_date),
        status=JournalEntry.Status.POSTED,
        reverses=entry,
        created_by=user,
        content_type=entry.content_type,
        object_id=entry.object_id,
        currency=entry.currency,
        exchange_rate=entry.exchange_rate,
    )
    JournalLine.objects.bulk_create(
        [
            JournalLine(
                entry=reversal,
                account=line.account,
                cost_center=line.cost_center,
                party=line.party,
                description=line.description,
                currency=line.currency,
                exchange_rate=line.exchange_rate,
                debit_fc=line.credit_fc,
                credit_fc=line.debit_fc,
                debit=line.credit,
                credit=line.debit,
            )
            for line in entry.lines.all()
        ]
    )
    entry.status = JournalEntry.Status.REVERSED
    entry.reversed_at = timezone.now()
    entry.save(update_fields=["status", "reversed_at"])
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER,
        actor_id=user.id,
        action="journal_entry.reversed",
        target_type="journal_entry",
        target_id=entry.id,
        tenant_id=tenant.id,
        after={"reason": reason, "reversal_entry_id": str(reversal.id)},
    )
    return reversal


def compute_trial_balance(tenant, legal_entity_id=None, date_from=None, date_to=None, legal_entity=None, include_children=True):
    """Sprint 4.4 (3.15.1): "ميزان مراجعة أولي" — a UAT verification
    tool, not the full drill-down report (sprint 10). Per leaf account:
    movement debit/credit and balance in base currency. Only POSTED/
    REVERSED entries ever contribute (see REPORTABLE_STATUSES) — total
    debit always equals total credit by construction, since it's
    summing only already-balanced entries.

    Sprint 6.6.7 (§2 item 2): `period_checklist`'s own trial-balance
    line passes a `LegalEntity` instance via `legal_entity` (subtree-
    scoped through `_entities_in_scope`, same as the four reports) —
    kept separate from the pre-existing `legal_entity_id` (a single id,
    no subtree) so the UAT trial-balance screen's own call shape never
    changes.
    """
    from django.db.models import Sum

    lines = JournalLine.objects.filter(entry__tenant=tenant, entry__status__in=REPORTABLE_STATUSES)
    if legal_entity is not None:
        from apps.reports.services import _entities_in_scope

        lines = lines.filter(entry__legal_entity__in=_entities_in_scope(legal_entity, include_children))
    elif legal_entity_id:
        lines = lines.filter(entry__legal_entity_id=legal_entity_id)
    if date_from:
        lines = lines.filter(entry__date__gte=date_from)
    if date_to:
        lines = lines.filter(entry__date__lte=date_to)

    totals = (
        lines.values(
            "account_id", "account__code", "account__name", "account__normal_balance", "account__level"
        )
        .annotate(debit=Sum("debit"), credit=Sum("credit"))
        .order_by("account__code")
    )
    rows = []
    total_debit = total_credit = Decimal("0")
    for row in totals:
        debit = row["debit"] or Decimal("0")
        credit = row["credit"] or Decimal("0")
        is_debit_normal = row["account__normal_balance"] == Account.NormalBalance.DEBIT
        balance = (debit - credit) if is_debit_normal else (credit - debit)
        rows.append(
            {
                "account_id": row["account_id"],
                "account_code": row["account__code"],
                "account_name": row["account__name"],
                "level": row["account__level"],
                "debit": debit,
                "credit": credit,
                "balance": balance,
            }
        )
        total_debit += debit
        total_credit += credit
    return {"rows": rows, "total_debit": total_debit, "total_credit": total_credit}


def ledger_lines(tenant, account, legal_entity=None, include_children=True, date_from=None, date_to=None, unreconciled=False):
    """Sprint 5.4 (docs/prompts/sprint-5.md block 5.4): the one query
    behind treasury movements (`apps.treasury.views`), party statements
    (`apps.parties.views.PartyViewSet.statement`) and, in 5.7 (C5), the
    general ledger screen — same principle as `treasury_balance`, just
    generalized to any account and to a running balance per line
    instead of one final total.

    `date_from` is inclusive for the period, exclusive for the opening
    balance (everything strictly before it is "opening"). Signs every
    running balance by the account's own `normal_balance` — debit-
    normal (asset/expense) balances grow on debit, credit-normal
    (liability/equity/revenue) balances grow on credit — so a caller
    never has to know or guess which one `account` is.

    Sprint 6.6.7 (§2 item 1 + §6.4): `legal_entity` scopes to that
    entity's own sub-tree by default (`include_children=True`, reusing
    `apps.reports.services._entities_in_scope` — a company-level report
    is the sum of its branches' own lines plus its own direct ones),
    and the running balance is computed by Postgres itself via a window
    function (one pass, no Python accumulation loop) to hit the <2s
    budget on 100k lines — purely through the ORM (`Window`/`F`/`Sum`),
    so it stays subject to the same RLS policies as every other query
    here, never a raw-SQL bypass of `cps.tenant_id`.
    """
    sign = 1 if account.normal_balance == Account.NormalBalance.DEBIT else -1

    base_qs = account.journal_lines.filter(entry__tenant=tenant, entry__status__in=REPORTABLE_STATUSES)
    if legal_entity is not None:
        from apps.reports.services import _entities_in_scope

        base_qs = base_qs.filter(entry__legal_entity__in=_entities_in_scope(legal_entity, include_children))

    opening_qs = base_qs
    if date_from is not None:
        opening_qs = opening_qs.filter(entry__date__lt=date_from)
    else:
        opening_qs = opening_qs.none()
    opening_totals = opening_qs.aggregate(
        debit=Sum("debit"), credit=Sum("credit"), debit_fc=Sum("debit_fc"), credit_fc=Sum("credit_fc")
    )
    opening_base = sign * ((opening_totals["debit"] or Decimal("0")) - (opening_totals["credit"] or Decimal("0")))
    opening_fc = sign * ((opening_totals["debit_fc"] or Decimal("0")) - (opening_totals["credit_fc"] or Decimal("0")))

    period_qs = base_qs
    if date_from is not None:
        period_qs = period_qs.filter(entry__date__gte=date_from)
    if date_to is not None:
        period_qs = period_qs.filter(entry__date__lte=date_to)
    if unreconciled:
        # Sprint 5.5 (block 5.5.2): the manual-matching screen's other
        # column — POSTED lines on this bank account not yet linked to
        # any statement line. Only narrows the returned `lines`, never
        # the opening-balance total above (still every POSTED line).
        period_qs = period_qs.filter(bank_statement_line__isnull=True)

    order = (F("entry__date").asc(), F("entry__number").asc(), F("id").asc())
    period_rows = (
        period_qs.annotate(
            cum_base=Window(expression=Sum((F("debit") - F("credit")) * sign), order_by=order),
            cum_fc=Window(expression=Sum((F("debit_fc") - F("credit_fc")) * sign), order_by=order),
        )
        .order_by(*order)
        .values(
            "id", "entry_id", "description", "debit", "credit", "debit_fc", "credit_fc", "currency",
            "cum_base", "cum_fc",
            "entry__date", "entry__number", "entry__memo", "entry__source_type", "entry__source_id",
        )
    )

    lines = [
        {
            "date": row["entry__date"],
            "entry_id": row["entry_id"],
            "entry_number": row["entry__number"],
            "description": row["description"] or row["entry__memo"],
            "debit": row["debit"], "credit": row["credit"],
            "debit_fc": row["debit_fc"], "credit_fc": row["credit_fc"], "currency": row["currency"],
            "running_balance": opening_base + row["cum_base"], "running_balance_fc": opening_fc + row["cum_fc"],
            "source_type": row["entry__source_type"], "source_id": row["entry__source_id"],
        }
        for row in period_rows
    ]
    closing_base = lines[-1]["running_balance"] if lines else opening_base
    closing_fc = lines[-1]["running_balance_fc"] if lines else opening_fc
    return {
        "opening_balance": opening_base, "opening_balance_fc": opening_fc,
        "lines": lines,
        "closing_balance": closing_base, "closing_balance_fc": closing_fc,
    }
