import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import Account, JournalEntry, JournalLine

CHART_TEMPLATES_DIR = Path(__file__).resolve().parent / "chart_templates"

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
        is_system=False,
    )
    instance.gl_account = account
    instance.save(update_fields=["gl_account"])
    return account


def build_journal_lines_with_fx_rounding(tenant, entry, line_specs, exchange_rate):
    """Sprint 4.2 (3.15.3), extended in 4.3 with the posting guard (3.4:
    "لا ترحيل على حساب له أبناء") and JournalLine.party auto-fill (3.4:
    "auto-filled when posting to a sub-ledger account").

    Converts each line_spec ({"account", "cost_center" (optional),
    "debit_fc", "credit_fc"}, amounts in entry.currency) into an
    unsaved JournalLine with debit/credit (legal_entity.base_currency)
    also populated — each line rounded to the cent independently
    (ROUND_HALF_UP), same as every other money computation in this
    project.

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
        lines.append(
            JournalLine(
                entry=entry,
                account=account,
                cost_center=spec.get("cost_center"),
                party=account.party,
                debit_fc=spec["debit_fc"],
                credit_fc=spec["credit_fc"],
                debit=(spec["debit_fc"] * exchange_rate).quantize(CENTS, rounding=ROUND_HALF_UP),
                credit=(spec["credit_fc"] * exchange_rate).quantize(CENTS, rounding=ROUND_HALF_UP),
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
        if diff > 0:
            lines.append(JournalLine(entry=entry, account=rounding_account, debit=diff, credit=Decimal("0")))
        else:
            lines.append(
                JournalLine(entry=entry, account=rounding_account, debit=Decimal("0"), credit=-diff)
            )
    return lines


@transaction.atomic
def post_invoice_journal_entry(invoice):
    """Post a balanced journal entry for an issued invoice.

    Debits the customer's own sub-ledger account (auto-created under
    CUSTOMERS, sprint 4.3 — not a shared lump "Accounts Receivable"
    bucket, so per-customer statements/aging can read JournalLine.party
    directly) for the invoice total, credits Sales Revenue for the
    subtotal and Tax Payable for the tax — always balanced by
    construction since credit total == debit total (in invoice.currency;
    build_journal_lines_with_fx_rounding handles the base-currency
    conversion and rounding, sprint 4.2).

    TECH DEBT (README "Technical debt"): the revenue/tax lines here are
    aggregated across all invoice lines, so JournalLine.cost_center is
    never populated by this function even when individual InvoiceLines
    carry one — distributing revenue per invoice-line cost center into
    separate journal lines is deferred to the reporting sprint (10),
    when cost-center P&L actually needs it. JournalLine.cost_center is
    usable today for manual journal entries.
    """
    tenant = invoice.tenant
    from apps.parties.models import PartyRole

    ar = get_or_create_party_role_account(invoice.party, PartyRole.Role.CUSTOMER)
    if ar is None:
        ar = _get_system_account_or_fallback(tenant, "CUSTOMERS")
    revenue = _get_system_account_or_fallback(tenant, "SALES")

    entry = JournalEntry.objects.create(
        tenant=tenant,
        legal_entity=invoice.legal_entity,
        date=invoice.issue_date,
        memo=f"Invoice {invoice.number}",
        source_type="invoice",
        source_id=invoice.id,
        currency=invoice.currency,
        exchange_rate=invoice.exchange_rate,
    )

    line_specs = [
        {"account": ar, "debit_fc": invoice.total, "credit_fc": Decimal("0")},
        {"account": revenue, "debit_fc": Decimal("0"), "credit_fc": invoice.subtotal},
    ]
    if invoice.tax_total:
        tax_payable = _get_system_account_or_fallback(tenant, "VAT_OUTPUT")
        line_specs.append(
            {"account": tax_payable, "debit_fc": Decimal("0"), "credit_fc": invoice.tax_total}
        )

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
    """
    original = JournalEntry.objects.get(
        tenant=invoice.tenant, source_type="invoice", source_id=invoice.id
    )
    reversal = JournalEntry.objects.create(
        tenant=invoice.tenant,
        legal_entity=invoice.legal_entity,
        date=timezone.localdate(),
        memo=f"Void of invoice {invoice.number}",
        source_type="invoice_void",
        source_id=invoice.id,
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
                debit_fc=line.credit_fc,
                credit_fc=line.debit_fc,
                debit=line.credit,
                credit=line.debit,
            )
            for line in original.lines.all()
        ]
    )
    return reversal
