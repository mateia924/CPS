"""Sprint 6.5 (block 6.5.0, decision 2; revised 6.5.6, decision C): the
four new fixed-asset system accounts (FIXED_ASSETS, ACCUM_DEPRECIATION,
DEPRECIATION_EXPENSE, DISPOSAL_GAIN_LOSS) — present on every activity
template, backfilled idempotently for existing tenants. Only the three
the depreciation/disposal engine itself posts to (ACCUM_DEPRECIATION,
DEPRECIATION_EXPENSE, DISPOSAL_GAIN_LOSS) are control accounts (no
direct manual posting without an override reason) — FIXED_ASSETS
itself is posted to normally, by a voucher or manual JV, for the
asset's own purchase or an addition (decision 1).
"""

import importlib
from datetime import date
from decimal import Decimal

import pytest

from apps.accounting.models import Account
from apps.accounting.services import create_manual_journal_entry, seed_chart_of_accounts
from apps.organization.models import LegalEntity

from .factories import TenantFactory

_SYSTEM_KEYS = ["FIXED_ASSETS", "ACCUM_DEPRECIATION", "DEPRECIATION_EXPENSE", "DISPOSAL_GAIN_LOSS"]
# Sprint 6.5.6 (UAT fix, decision C): FIXED_ASSETS stopped being a
# control account — the asset's own purchase (or an addition) is
# posted normally via a voucher or manual JV like any other capital
# expenditure (decision 1); only the three accounts the depreciation/
# disposal engine itself owns stay control accounts.
_CONTROL_SYSTEM_KEYS = ["ACCUM_DEPRECIATION", "DEPRECIATION_EXPENSE", "DISPOSAL_GAIN_LOSS"]

_backfill_module = importlib.import_module("apps.accounting.migrations.0027_backfill_fixed_asset_accounts")


def _branch(tenant):
    return LegalEntity.objects.get(tenant=tenant, entity_type=LegalEntity.Type.BRANCH)


@pytest.mark.django_db
@pytest.mark.parametrize("business_type", ["service", "trading", "manufacturing", "holding"])
def test_new_tenant_gets_all_four_accounts_on_every_template(business_type):
    tenant = TenantFactory(subdomain=f"assets-accounts-{business_type}", business_type=business_type)
    seed_chart_of_accounts(tenant)
    for key in _SYSTEM_KEYS:
        account = Account.objects.get(tenant=tenant, system_key=key)
        assert account.allow_manual_posting == (key not in _CONTROL_SYSTEM_KEYS)


@pytest.mark.django_db
def test_backfill_migration_is_idempotent_on_existing_tenant(tenant_a):
    # tenant_a (conftest.py) already has a chart seeded before this
    # block existed — simulate that by removing the four accounts a
    # normal `seed_chart_of_accounts` call would already include, then
    # run the real migration function twice.
    Account.objects.filter(tenant=tenant_a, system_key__in=_SYSTEM_KEYS).delete()

    from django.apps import apps as django_apps

    _backfill_module.backfill_fixed_asset_accounts(django_apps, None)
    first_count = Account.objects.filter(tenant=tenant_a, system_key__in=_SYSTEM_KEYS).count()
    assert first_count == 4

    _backfill_module.backfill_fixed_asset_accounts(django_apps, None)
    second_count = Account.objects.filter(tenant=tenant_a, system_key__in=_SYSTEM_KEYS).count()
    assert second_count == 4


@pytest.mark.django_db
def test_backfill_skips_tenant_with_no_chart(db):
    tenant = TenantFactory(subdomain="assets-no-chart")
    from django.apps import apps as django_apps

    _backfill_module.backfill_fixed_asset_accounts(django_apps, None)
    assert Account.objects.filter(tenant=tenant, system_key__in=_SYSTEM_KEYS).count() == 0


@pytest.mark.django_db
def test_direct_manual_posting_to_accum_depreciation_rejected_without_override(tenant_a, user_a):
    accum = Account.objects.get(tenant=tenant_a, system_key="ACCUM_DEPRECIATION")
    other = Account.objects.get(tenant=tenant_a, system_key="CASH")

    with pytest.raises(Exception):
        create_manual_journal_entry(
            tenant=tenant_a, user=user_a, legal_entity=_branch(tenant_a), date=date(2026, 1, 5),
            line_specs=[
                {"account": accum, "debit_fc": Decimal("100.00"), "credit_fc": Decimal("0")},
                {"account": other, "debit_fc": Decimal("0"), "credit_fc": Decimal("100.00")},
            ],
            currency="SAR", exchange_rate=Decimal("1"),
        )


@pytest.mark.django_db
def test_direct_manual_posting_to_fixed_assets_allowed_without_override(tenant_a, user_a):
    """Sprint 6.5.6 (UAT fix, decision C): buying an asset (or adding
    to one) is an ordinary manual JV/voucher on FIXED_ASSETS, exactly
    like any other capital expenditure — no control-account override
    reason needed, unlike ACCUM_DEPRECIATION/DEPRECIATION_EXPENSE/
    DISPOSAL_GAIN_LOSS above, which the depreciation engine still owns
    exclusively."""
    fixed_assets = Account.objects.get(tenant=tenant_a, system_key="FIXED_ASSETS")
    cash = Account.objects.get(tenant=tenant_a, system_key="CASH")

    entry = create_manual_journal_entry(
        tenant=tenant_a, user=user_a, legal_entity=_branch(tenant_a), date=date(2026, 1, 5),
        line_specs=[
            {"account": fixed_assets, "debit_fc": Decimal("1000.00"), "credit_fc": Decimal("0")},
            {"account": cash, "debit_fc": Decimal("0"), "credit_fc": Decimal("1000.00")},
        ],
        currency="SAR", exchange_rate=Decimal("1"),
    )
    assert entry.is_control_override is False


@pytest.mark.django_db
def test_tenant_isolation(tenant_a, tenant_b):
    account_a = Account.objects.get(tenant=tenant_a, system_key="FIXED_ASSETS")
    assert not Account.objects.filter(tenant=tenant_b, id=account_a.id).exists()


def _asset_payload(tenant, **overrides):
    payload = {
        "legal_entity": str(_branch(tenant).id), "code": "AST-TEST", "name": "Test asset",
        "category": "equipment", "purchase_date": "2026-01-01", "purchase_cost": "10000.00",
        "salvage_value": "1000.00", "useful_life_months": 36,
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
def test_salvage_must_be_less_than_purchase_cost(tenant_a, client_a):
    response = client_a.post(
        "/api/assets/", _asset_payload(tenant_a, purchase_cost="1000.00", salvage_value="1000.00"), format="json"
    )
    assert response.status_code == 400, response.data
    assert "salvage_value" in response.data


@pytest.mark.django_db
def test_useful_life_must_be_at_least_one_month(tenant_a, client_a):
    response = client_a.post("/api/assets/", _asset_payload(tenant_a, useful_life_months=0), format="json")
    assert response.status_code == 400, response.data
    assert "useful_life_months" in response.data


@pytest.mark.django_db
def test_declining_balance_rate_required_only_with_declining_method(tenant_a, client_a):
    missing_rate = client_a.post(
        "/api/assets/", _asset_payload(tenant_a, depreciation_method="declining_balance"), format="json"
    )
    assert missing_rate.status_code == 400, missing_rate.data
    assert "declining_balance_rate" in missing_rate.data

    out_of_range = client_a.post(
        "/api/assets/",
        _asset_payload(tenant_a, depreciation_method="declining_balance", declining_balance_rate="150"),
        format="json",
    )
    assert out_of_range.status_code == 400, out_of_range.data

    valid = client_a.post(
        "/api/assets/",
        _asset_payload(tenant_a, depreciation_method="declining_balance", declining_balance_rate="40"),
        format="json",
    )
    assert valid.status_code == 201, valid.data
