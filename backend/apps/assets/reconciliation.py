"""Sprint 6.5 (decisions 10, 13): the one register-vs-ledger
reconciliation computation — used by the period-close checklist
(6.5.1) and the fixed-asset register report's footer (6.5.5), so the
two screens can never silently disagree about whether the subsidiary
register (apps.assets.models.Asset) matches the chart of accounts.

Written to need no changes when additions (6.5.3) or disposal (6.5.4)
land: `Asset.cost_base` is already updated in place by an addition,
and a disposal's `disposed_fraction` already scales both cost and
accumulated depreciation down by the same fraction the ledger's own
disposal entry credits/debits — see decision 7.
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
    """The subsidiary register's own totals, net of `disposed_fraction`."""
    as_of = as_of or timezone.localdate()
    assets = Asset.objects.filter(tenant=tenant, is_active=True, purchase_date__lte=as_of)
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
        total_accum += accum * remaining_fraction
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
