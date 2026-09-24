"""Sprint 6.8 (decision 19, F9/D5): TenantFeatures.cost_center_required
— once on, a manual journal entry line on a revenue/expense account
with no cost_center is rejected; before enabling (the default) it
passes as before. Wired through apps.accounting.services.
check_cost_center_required, called from create_manual_journal_entry and
apps.vouchers.services._build_posting_specs (account lines only).
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.accounting.models import Account
from apps.accounting.services import create_manual_journal_entry
from apps.organization.models import LegalEntity
from apps.tenants.models import TenantFeatures

from .factories import CostCenterFactory


def _leaf_pair(tenant):
    cash = Account.objects.get(tenant=tenant, system_key="CASH")
    sales = Account.objects.get(tenant=tenant, system_key="SALES")
    return cash, sales


def _entity(tenant):
    return LegalEntity.objects.get(tenant=tenant, entity_type=LegalEntity.Type.BRANCH)


@pytest.mark.django_db
def test_revenue_line_without_cost_center_passes_before_toggle(tenant_a, user_a):
    cash, sales = _leaf_pair(tenant_a)
    entry = create_manual_journal_entry(
        tenant=tenant_a, user=user_a, legal_entity=_entity(tenant_a), date=date(2026, 1, 5),
        line_specs=[
            {"account": cash, "debit_fc": Decimal("50.00"), "credit_fc": Decimal("0")},
            {"account": sales, "debit_fc": Decimal("0"), "credit_fc": Decimal("50.00")},
        ],
        currency="SAR", exchange_rate=Decimal("1"),
    )
    assert entry.id is not None


@pytest.mark.django_db
def test_revenue_line_without_cost_center_rejected_after_toggle(tenant_a, user_a):
    TenantFeatures.objects.filter(tenant_id=tenant_a.id).update(cost_center_required=True)
    cash, sales = _leaf_pair(tenant_a)
    with pytest.raises(Exception) as exc_info:
        create_manual_journal_entry(
            tenant=tenant_a, user=user_a, legal_entity=_entity(tenant_a), date=date(2026, 1, 5),
            line_specs=[
                {"account": cash, "debit_fc": Decimal("50.00"), "credit_fc": Decimal("0")},
                {"account": sales, "debit_fc": Decimal("0"), "credit_fc": Decimal("50.00")},
            ],
            currency="SAR", exchange_rate=Decimal("1"),
        )
    assert "مركز تكلفة" in str(exc_info.value)


@pytest.mark.django_db
def test_revenue_line_with_cost_center_passes_after_toggle(tenant_a, user_a):
    TenantFeatures.objects.filter(tenant_id=tenant_a.id).update(cost_center_required=True)
    cash, sales = _leaf_pair(tenant_a)
    cost_center = CostCenterFactory(tenant=tenant_a)
    entry = create_manual_journal_entry(
        tenant=tenant_a, user=user_a, legal_entity=_entity(tenant_a), date=date(2026, 1, 5),
        line_specs=[
            {"account": cash, "debit_fc": Decimal("50.00"), "credit_fc": Decimal("0")},
            {"account": sales, "debit_fc": Decimal("0"), "credit_fc": Decimal("50.00"), "cost_center": cost_center},
        ],
        currency="SAR", exchange_rate=Decimal("1"),
    )
    assert entry.id is not None
