"""Sprint 6.5 (decisions 10, 13): the one register-vs-ledger
reconciliation computation — used by the period-close checklist
(6.5.1) and the fixed-asset register report's footer (6.5.5), so the
two screens can never silently disagree about whether the subsidiary
register (apps.assets.models.Asset) matches the chart of accounts.

Needed no changes for additions (6.5.3): `Asset.cost_base` is already
updated in place by add_to_asset. Disposal (6.5.4) needed one: see
register_totals's own docstring for why accumulated depreciation is
not re-scaled by `disposed_fraction` the same way cost is.
"""

from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from apps.accounting.models import RecurringInstallment
from apps.accounting.services import get_system_account
from apps.reports.services import _entities_in_scope, account_balances

from .models import Asset

CENTS = Decimal("0.01")


def register_totals(tenant, as_of=None, legal_entity=None, include_children=True):
    """The subsidiary register's own totals.

    Cost is scaled by `remaining_fraction` (1 − disposed_fraction) —
    valid because `cost_base` is never mutated by a disposal, so
    disposal fractions telescope cleanly against it (decision 7:
    cost_share_i = fraction_i × the one constant cost_base, so Σ
    cost_share = disposed_fraction × cost_base exactly).

    Accumulated depreciation is *not* re-scaled the same way: decisions
    6/7 (apps.assets.depreciation._reschedule_remaining) lock in each
    now-cancelled entry's own generated total into `opening_
    accumulated_depreciation` at reschedule time — net of a disposal's
    own accum_share, since that's exactly what the ledger's disposal
    entry debits out of ACCUM_DEPRECIATION too — so
    `opening_accumulated_depreciation + the current entry's own
    generated total` is already the correct absolute remaining figure,
    with no further scaling needed (and re-scaling it would double-
    count the effect of a disposal that already happened once).
    A fully DISPOSED asset contributes nothing at all.
    """
    as_of = as_of or timezone.localdate()
    assets = Asset.objects.filter(tenant=tenant, is_active=True, purchase_date__lte=as_of).exclude(
        status=Asset.Status.DISPOSED
    )
    if legal_entity is not None:
        assets = assets.filter(legal_entity__in=_entities_in_scope(legal_entity, include_children))

    total_cost = Decimal("0")
    total_accum = Decimal("0")
    for asset in assets.select_related("depreciation_entry"):
        remaining_fraction = Decimal("1") - asset.disposed_fraction
        cost = asset.cost_base if asset.cost_base is not None else asset.purchase_cost
        accum = asset.opening_accumulated_depreciation
        if asset.depreciation_entry_id:
            generated = (
                RecurringInstallment.objects.filter(
                    entry_id=asset.depreciation_entry_id,
                    status=RecurringInstallment.Status.GENERATED,
                    due_date__lte=as_of,
                ).aggregate(total=Sum("amount_base"))["total"]
                or Decimal("0")
            )
            accum += generated
        total_cost += cost * remaining_fraction
        total_accum += accum
    return {
        "cost": total_cost.quantize(CENTS),
        "accumulated_depreciation": total_accum.quantize(CENTS),
    }


def register_vs_ledger(tenant, as_of=None, legal_entity=None, include_children=True):
    """Decision 13's reconciliation footer, decision 10's period-close
    WARN — one implementation. `ledger_accumulated_depreciation` is
    reported as a positive figure (the negative-under-assets
    presentation, decision 2 of 6.5.0, is a display concern of the
    balance sheet only) so it compares directly against the register's
    own positive total."""
    register = register_totals(tenant, as_of=as_of, legal_entity=legal_entity, include_children=include_children)
    balances = account_balances(tenant, legal_entity=legal_entity, include_children=include_children, date_to=as_of)

    def _closing_for(system_key):
        account = get_system_account(tenant, system_key)
        if account is None:
            return Decimal("0")
        return (balances.get(account.id) or {}).get("closing", Decimal("0"))

    ledger_cost = _closing_for("FIXED_ASSETS")
    ledger_accum = -_closing_for("ACCUM_DEPRECIATION")

    return {
        "register_cost": register["cost"],
        "ledger_cost": ledger_cost,
        "cost_diff": register["cost"] - ledger_cost,
        "register_accumulated_depreciation": register["accumulated_depreciation"],
        "ledger_accumulated_depreciation": ledger_accum,
        "accum_diff": register["accumulated_depreciation"] - ledger_accum,
    }
