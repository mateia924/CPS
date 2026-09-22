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
