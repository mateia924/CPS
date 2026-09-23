from decimal import Decimal

from django.utils.translation import gettext_lazy as _

from .models import ExchangeRate


class ExchangeRateNotFound(Exception):
    """Raised by get_rate below; callers turn this into a 400 with the
    Arabic message attached."""

    def __init__(self, message):
        self.message = message
        super().__init__(message)


def get_rate(tenant, from_currency, to_currency, date):
    """Sprint 4.2 (docs/SYSTEM_ANALYSIS.md 3.15.3): the most recent rate
    with date <= the requested date — never a future rate, and never an
    average/interpolation. Same currency is always 1 (no DB lookup, no
    row needed)."""
    if from_currency == to_currency:
        return Decimal("1")

    rate_row = (
        ExchangeRate.objects.filter(
            tenant=tenant, from_currency=from_currency, to_currency=to_currency, date__lte=date
        )
        .order_by("-date")
        .first()
    )
    if rate_row is None:
        raise ExchangeRateNotFound(
            _("لا يوجد سعر صرف مسجَّل من %(from)s إلى %(to)s بتاريخ %(date)s أو قبله.")
            % {"from": from_currency, "to": to_currency, "date": date}
        )
    return rate_row.rate


def treasury_balance(tenant, kind, treasury_id, as_of=None):
    """Sprint 5.3/5.4: current running balance of a Bank/CashBox/
    Custody's gl_account, from POSTED/REVERSED journal lines only
    (apps.accounting.services.REPORTABLE_STATUSES) — the single service
    `ledger_lines()` (5.7) will later be built on the same querying
    principle for the full statements. Returns both the base-currency
    balance and the account's own currency balance (debit_fc/credit_fc
    — always in one consistent currency per account, since every
    voucher's currency is pinned to its treasury account's own
    currency by construction, decision 4).
    """
    from django.db.models import Sum

    from apps.accounting.services import REPORTABLE_STATUSES
    from apps.treasury.models import Bank, CashBox, Custody

    model = {"bank": Bank, "cash_box": CashBox, "custody": Custody}[kind]
    instance = model.objects.get(tenant=tenant, id=treasury_id)
    account = instance.gl_account
    if account is None:
        return {"base": Decimal("0"), "fc": Decimal("0")}

    lines = account.journal_lines.filter(entry__tenant=tenant, entry__status__in=REPORTABLE_STATUSES)
    if as_of is not None:
        lines = lines.filter(entry__date__lte=as_of)
    totals = lines.aggregate(
        debit=Sum("debit"), credit=Sum("credit"), debit_fc=Sum("debit_fc"), credit_fc=Sum("credit_fc")
    )
    # Treasury accounts are always ASSET/debit-normal.
    base = (totals["debit"] or Decimal("0")) - (totals["credit"] or Decimal("0"))
    fc = (totals["debit_fc"] or Decimal("0")) - (totals["credit_fc"] or Decimal("0"))
    return {"base": base, "fc": fc}
