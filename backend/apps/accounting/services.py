from decimal import Decimal

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
]

# Codes the invoice-posting flow depends on. Kept as constants so the
# service functions below don't hardcode magic strings in two places.
ACCOUNTS_RECEIVABLE_CODE = "1100"
SALES_REVENUE_CODE = "4000"
TAX_PAYABLE_CODE = "2100"


def seed_chart_of_accounts(tenant):
    """Create the default chart of accounts for a brand-new tenant."""
    Account.objects.bulk_create(
        [
            Account(tenant=tenant, code=code, name=name, type=type_, is_system=True)
            for code, name, type_ in DEFAULT_CHART_OF_ACCOUNTS
        ]
    )


@transaction.atomic
def post_invoice_journal_entry(invoice):
    """Post a balanced journal entry for an issued invoice.

    Debits Accounts Receivable for the invoice total, credits Sales
    Revenue for the subtotal and Tax Payable for the tax — always
    balanced by construction since credit total == debit total.

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
    )

    lines = [
        JournalLine(entry=entry, account=ar, debit=invoice.total, credit=Decimal("0")),
        JournalLine(entry=entry, account=revenue, debit=Decimal("0"), credit=invoice.subtotal),
    ]
    if invoice.tax_total:
        tax_payable = Account.objects.get(tenant=tenant, code=TAX_PAYABLE_CODE)
        lines.append(
            JournalLine(entry=entry, account=tax_payable, debit=Decimal("0"), credit=invoice.tax_total)
        )
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
    )
    JournalLine.objects.bulk_create(
        [
            JournalLine(
                entry=reversal,
                account=line.account,
                cost_center=line.cost_center,
                debit=line.credit,
                credit=line.debit,
            )
            for line in original.lines.all()
        ]
    )
    return reversal
