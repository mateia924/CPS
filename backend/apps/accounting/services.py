from decimal import Decimal

from django.db import transaction
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
    """
    tenant = invoice.tenant
    ar = Account.objects.get(tenant=tenant, code=ACCOUNTS_RECEIVABLE_CODE)
    revenue = Account.objects.get(tenant=tenant, code=SALES_REVENUE_CODE)

    entry = JournalEntry.objects.create(
        tenant=tenant,
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
