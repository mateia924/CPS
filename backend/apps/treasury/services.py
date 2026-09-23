import logging
from decimal import ROUND_HALF_UP, Decimal

from django.utils.translation import gettext_lazy as _

from .models import ExchangeRate

logger = logging.getLogger(__name__)

RATE_QUANT = Decimal("0.00000001")
STALE_RATE_DAYS = 7


class ExchangeRateNotFound(Exception):
    """Raised by get_rate below; callers turn this into a 400 with the
    Arabic message attached."""

    def __init__(self, message):
        self.message = message
        super().__init__(message)


def _find_rate_row(tenant, from_currency, to_currency, date):
    """CFO_REVIEW_1 C14: the direct pair first; if it's never been
    recorded, fall back to the reverse pair's most recent row and let
    the caller invert it (1/rate) — returns (row, inverted: bool) or
    (None, False). Logged (not raised) since this is an expected,
    correct fallback, not an error."""
    row = (
        ExchangeRate.objects.filter(
            tenant=tenant, from_currency=from_currency, to_currency=to_currency, date__lte=date
        )
        .order_by("-date")
        .first()
    )
    if row is not None:
        return row, False

    reverse_row = (
        ExchangeRate.objects.filter(
            tenant=tenant, from_currency=to_currency, to_currency=from_currency, date__lte=date
        )
        .order_by("-date")
        .first()
    )
    if reverse_row is not None:
        logger.info(
            "get_rate: no %s->%s rate for tenant %s as of %s — inferred from the recorded %s->%s rate (1/rate).",
            from_currency, to_currency, tenant.id, date, to_currency, from_currency,
        )
        return reverse_row, True
    return None, False


def get_rate(tenant, from_currency, to_currency, date):
    """Sprint 4.2 (docs/SYSTEM_ANALYSIS.md 3.15.3): the most recent rate
    with date <= the requested date — never a future rate, and never an
    average/interpolation. Same currency is always 1 (no DB lookup, no
    row needed). CFO_REVIEW_1 C14: infers the inverse (1/rate) from the
    reverse pair when the direct pair was never recorded."""
    if from_currency == to_currency:
        return Decimal("1")

    row, inverted = _find_rate_row(tenant, from_currency, to_currency, date)
    if row is None:
        raise ExchangeRateNotFound(
            _("لا يوجد سعر صرف مسجَّل من %(from)s إلى %(to)s بتاريخ %(date)s أو قبله.")
            % {"from": from_currency, "to": to_currency, "date": date}
        )
    if inverted:
        return (Decimal("1") / row.rate).quantize(RATE_QUANT, rounding=ROUND_HALF_UP)
    return row.rate


def get_rate_with_warnings(tenant, from_currency, to_currency, date):
    """Same resolution as get_rate, plus a `warnings[]` entry when the
    resolved rate's own recorded date is more than STALE_RATE_DAYS
    before the requested date (CFO_REVIEW_1 C14) — for callers that
    already surface a warnings list to the user (e.g. vouchers)."""
    if from_currency == to_currency:
        return Decimal("1"), []

    row, inverted = _find_rate_row(tenant, from_currency, to_currency, date)
    if row is None:
        raise ExchangeRateNotFound(
            _("لا يوجد سعر صرف مسجَّل من %(from)s إلى %(to)s بتاريخ %(date)s أو قبله.")
            % {"from": from_currency, "to": to_currency, "date": date}
        )
    rate = (Decimal("1") / row.rate).quantize(RATE_QUANT, rounding=ROUND_HALF_UP) if inverted else row.rate
    warnings = []
    age_days = (date - row.date).days
    if age_days > STALE_RATE_DAYS:
        warnings.append(
            str(
                _("سعر الصرف المستخدَم أقدم من %(days)s أيام (بتاريخ %(rate_date)s) — تحقّق منه.")
                % {"days": age_days, "rate_date": row.date}
            )
        )
    return rate, warnings


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
