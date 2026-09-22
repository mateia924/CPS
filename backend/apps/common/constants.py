"""Shared Decimal field precision constants (arch review #1, 2026-09-22
— docs/ARCH_REVIEW_1.md section 1.3): every money/price/quantity/
percentage DecimalField across the project used the same handful of
(max_digits, decimal_places) pairs, but as literal numbers repeated in
8 fields across 3 files. Naming them here means changing precision
(e.g. adding exchange-rate support at 18,8) is a one-line change
instead of an audit across every model file.

Values are unchanged from what was already in use — this is a pure
rename, not a schema change (no migration needed).
"""

MONEY_MAX_DIGITS = 14
MONEY_DECIMAL_PLACES = 2

PRICE_MAX_DIGITS = 12
PRICE_DECIMAL_PLACES = 2

QUANTITY_MAX_DIGITS = 12
QUANTITY_DECIMAL_PLACES = 2

PERCENTAGE_MAX_DIGITS = 5
PERCENTAGE_DECIMAL_PLACES = 2
