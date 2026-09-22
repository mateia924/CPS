from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import Account, JournalEntry, JournalLine

DEFAULT_CHART_OF_ACCOUNTS = [
    ("1000", _("Cash"), Account.Type.ASSET),
    ("1100", _("Accounts Receivable"), Account.Type.ASSET),
    ("2100", _("Tax Payable"), Account.Type.LIABILITY),
    ("3000", _("Owner's Equity"), Account.Type.EQUITY),
    ("4000", _("Sales Revenue"), Account.Type.REVENUE),
    ("5000", _("General Expenses"), Account.Type.EXPENSE),
    # Sprint 4.2 (3.15.3): absorbs the <=0.05 rounding gap that can
    # appear when each line of a foreign-currency entry is converted to
    # base currency independently — see build_journal_lines_with_fx_rounding.
    ("9100", _("Currency Rounding Differences"), Account.Type.EXPENSE),
]

# Codes the invoice-posting flow depends on. Kept as constants so the
# service functions below don't hardcode magic strings in two places.
ACCOUNTS_RECEIVABLE_CODE = "1100"
SALES_REVENUE_CODE = "4000"
TAX_PAYABLE_CODE = "2100"
# TODO(sprint 4.3): the chart-of-accounts rebuild introduces per-account
# `system_key` (ARCH_REVIEW_1.md §3.4's "قوالب الدليل") — once that
# lands, every *_CODE constant here (including this one) should become a
# system_key lookup instead of a hardcoded code, which breaks if a
# tenant's chart doesn't happen to use these exact numbers. Documented
# now rather than silently left as a gap.
FX_ROUNDING_ACCOUNT_CODE = "9100"

CENTS = Decimal("0.01")
FX_ROUNDING_TOLERANCE = Decimal("0.05")


def seed_chart_of_accounts(tenant):
    """Create the default chart of accounts for a brand-new tenant."""
    Account.objects.bulk_create(
        [
            Account(tenant=tenant, code=code, name=name, type=type_, is_system=True)
            for code, name, type_ in DEFAULT_CHART_OF_ACCOUNTS
        ]
    )


def build_journal_lines_with_fx_rounding(tenant, entry, line_specs, exchange_rate):
    """Sprint 4.2 (3.15.3): converts each line_spec ({"account",
    "cost_center" (optional), "debit_fc", "credit_fc"}, amounts in
    entry.currency) into an unsaved JournalLine with debit/credit
    (legal_entity.base_currency) also populated — each line rounded to
    the cent independently (ROUND_HALF_UP), same as every other money
    computation in this project.

    Converting each line separately can leave the base-currency debit
    and credit totals off by a few cents even though the fc totals are
    exactly balanced (rounding is not linear) — "التوازن إلزامي
    بالعملتين ... وفرق التقريب (≤ 0.05) يُضاف لسطر تقريب تلقائي". A gap
    bigger than that tolerance means a real bug upstream, not rounding
    noise, so it raises instead of silently absorbing it.
    """
    lines = [
        JournalLine(
            entry=entry,
            account=spec["account"],
            cost_center=spec.get("cost_center"),
            debit_fc=spec["debit_fc"],
            credit_fc=spec["credit_fc"],
            debit=(spec["debit_fc"] * exchange_rate).quantize(CENTS, rounding=ROUND_HALF_UP),
            credit=(spec["credit_fc"] * exchange_rate).quantize(CENTS, rounding=ROUND_HALF_UP),
        )
        for spec in line_specs
    ]

    debit_total = sum((line.debit for line in lines), Decimal("0"))
    credit_total = sum((line.credit for line in lines), Decimal("0"))
    diff = credit_total - debit_total
    if diff != 0:
        if abs(diff) > FX_ROUNDING_TOLERANCE:
            raise ValueError(
                f"FX conversion rounding gap {diff} exceeds the {FX_ROUNDING_TOLERANCE} "
                "tolerance — this indicates a real bug upstream, not rounding noise."
            )
        rounding_account = Account.objects.get(tenant=tenant, code=FX_ROUNDING_ACCOUNT_CODE)
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

    Debits Accounts Receivable for the invoice total, credits Sales
    Revenue for the subtotal and Tax Payable for the tax — always
    balanced by construction since credit total == debit total (in
    invoice.currency; build_journal_lines_with_fx_rounding handles the
    base-currency conversion and rounding, sprint 4.2).

    TECH DEBT (README "Technical debt"): the revenue/tax lines here are
    aggregated across all invoice lines, so JournalLine.cost_center is
    never populated by this function even when individual InvoiceLines
    carry one — distributing revenue per invoice-line cost center into
    separate journal lines is deferred to the reporting sprint (10),
    when cost-center P&L actually needs it. JournalLine.cost_center is
    usable today for manual journal entries.
    """
    tenant = invoice.tenant
    ar = Account.objects.get(tenant=tenant, code=ACCOUNTS_RECEIVABLE_CODE)
    revenue = Account.objects.get(tenant=tenant, code=SALES_REVENUE_CODE)

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
        tax_payable = Account.objects.get(tenant=tenant, code=TAX_PAYABLE_CODE)
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
                debit_fc=line.credit_fc,
                credit_fc=line.debit_fc,
                debit=line.credit,
                credit=line.debit,
            )
            for line in original.lines.all()
        ]
    )
    return reversal
