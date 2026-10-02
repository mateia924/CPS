"""Sprint 6.6.6 (§6.3 addition): the one place a money amount gets
interpolated into a user-facing (Arabic) message string — a plain
f-string/`%s` on a Decimal has no thousands separator ("10000.00"
instead of "10,000.00", the live bug in opening_balances.py's own
unbalanced-submit error), the exact gap frontend/src/lib/money.ts's
`formatMoney` already closes for every in-app numeric display.
"""

from decimal import Decimal


def format_money(amount) -> str:
    return f"{Decimal(amount):,.2f}"
