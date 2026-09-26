"""Sprint 6.5 (block 6.5.3, decision 6): capital additions to an
asset — cancel the remaining installments of the current depreciation
schedule and start a fresh one over the new book value, spread across
(remaining installments + extend_life_months). Real HTTP API + real
Postgres throughout (§11)."""

from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounting.models import RecurringEntry, RecurringInstallment
from apps.accounting.periods import close_period
from apps.accounting.recurring import generate_due_installments
from apps.assets.models import Asset

from .factories import AssetFactory, LegalEntityFactory


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _entity(tenant):
    return LegalEntityFactory(tenant=tenant)


def _start(client, asset_id):
    return client.post(f"/api/assets/{asset_id}/start-depreciation/")


def _period(tenant, seq, year="2026"):
    from apps.accounting.models import FiscalPeriod

    return FiscalPeriod.objects.get(fiscal_year__tenant=tenant, fiscal_year__name=year, seq=seq)


@pytest.fixture
def owner_client(user_a):
    return _client(user_a)


def _asset_with_running_schedule(tenant, entity, owner_client, **overrides):
    defaults = {
        "purchase_date": "2026-01-01", "purchase_cost": "12000.00", "salvage_value": "0", "useful_life_months": 12,
    }
    defaults.update(overrides)
    asset = AssetFactory(tenant=tenant, legal_entity=entity, **defaults)
    started = _start(owner_client, asset.id)
    assert started.status_code == 201, started.data
    asset.refresh_from_db()
    return asset


def test_addition_preserves_generated_installments_and_reschedules_the_rest(tenant_a, owner_client):
    entity = _entity(tenant_a)
    asset = _asset_with_running_schedule(tenant_a, entity, owner_client)
    old_entry_id = asset.depreciation_entry_id

    generate_due_installments(tenant=tenant_a, as_of=date(2026, 6, 30))
    old_amounts_1_6 = list(
        RecurringInstallment.objects.filter(entry_id=old_entry_id).order_by("seq").values_list("amount_base", flat=True)
    )[:6]
    assert old_amounts_1_6 == [Decimal("1000.00")] * 6

    response = owner_client.post(
        f"/api/assets/{asset.id}/additions/",
        {"date": "2026-06-20", "amount_base": "2400.00", "description": "تحسين"},
        format="json",
    )
    assert response.status_code == 201, response.data

    # Installments 1-6 on the OLD entry are untouched.
    unchanged = list(
        RecurringInstallment.objects.filter(entry_id=old_entry_id, seq__lte=6).order_by("seq").values_list("amount_base", flat=True)
    )
    assert unchanged == [Decimal("1000.00")] * 6
    old_entry = RecurringEntry.objects.get(id=old_entry_id)
    assert old_entry.status == RecurringEntry.Status.CANCELLED
    assert not old_entry.installments.filter(status=RecurringInstallment.Status.DUE).exists()

    asset.refresh_from_db()
    new_entry = asset.depreciation_entry
    assert new_entry.id != old_entry_id
    new_amounts = list(new_entry.installments.order_by("seq").values_list("amount_base", flat=True))
    assert new_amounts == [Decimal("1400.00")] * 6
    assert new_entry.first_period == _period(tenant_a, 7)


def test_addition_with_extended_life(tenant_a, owner_client):
    entity = _entity(tenant_a)
    asset = _asset_with_running_schedule(tenant_a, entity, owner_client)
    generate_due_installments(tenant=tenant_a, as_of=date(2026, 6, 30))

    response = owner_client.post(
        f"/api/assets/{asset.id}/additions/",
        {"date": "2026-06-20", "amount_base": "2400.00", "extend_life_months": 6},
        format="json",
    )
    assert response.status_code == 201, response.data

    asset.refresh_from_db()
    new_amounts = list(asset.depreciation_entry.installments.order_by("seq").values_list("amount_base", flat=True))
    assert new_amounts == [Decimal("700.00")] * 12


def test_addition_in_closed_period_returns_400(tenant_a, owner_client, user_a):
    entity = _entity(tenant_a)
    asset = _asset_with_running_schedule(tenant_a, entity, owner_client)
    generate_due_installments(tenant=tenant_a, as_of=date(2026, 6, 30))
    for seq in range(1, 7):
        close_period(_period(tenant_a, seq), user_a, acknowledge_warnings=True)

    response = owner_client.post(
        f"/api/assets/{asset.id}/additions/", {"date": "2026-03-15", "amount_base": "1000.00"}, format="json",
    )
    assert response.status_code == 400, response.data


def test_addition_without_active_schedule_returns_409(tenant_a, owner_client):
    entity = _entity(tenant_a)
    asset = AssetFactory(
        tenant=tenant_a, legal_entity=entity, purchase_date="2026-01-01", purchase_cost="12000.00",
        salvage_value="0", useful_life_months=12,
    )
    response = owner_client.post(
        f"/api/assets/{asset.id}/additions/", {"date": "2026-06-20", "amount_base": "1000.00"}, format="json",
    )
    assert response.status_code == 409, response.data


def test_addition_amount_must_be_positive(tenant_a, owner_client):
    entity = _entity(tenant_a)
    asset = _asset_with_running_schedule(tenant_a, entity, owner_client)
    response = owner_client.post(
        f"/api/assets/{asset.id}/additions/", {"date": "2026-02-01", "amount_base": "0"}, format="json",
    )
    assert response.status_code == 400, response.data


def test_addition_on_declining_balance_asset_recomputes_on_new_book_value(tenant_a, owner_client):
    entity = _entity(tenant_a)
    asset = _asset_with_running_schedule(
        tenant_a, entity, owner_client, purchase_cost="10000.00", salvage_value="1000.00", useful_life_months=36,
        depreciation_method=Asset.DepreciationMethod.DECLINING_BALANCE, declining_balance_rate="40",
    )
    generate_due_installments(tenant=tenant_a, as_of=date(2026, 6, 30))

    response = owner_client.post(
        f"/api/assets/{asset.id}/additions/", {"date": "2026-06-20", "amount_base": "1000.00"}, format="json",
    )
    assert response.status_code == 201, response.data

    asset.refresh_from_db()
    new_entry = asset.depreciation_entry
    amounts = list(new_entry.installments.order_by("seq").values_list("amount_base", flat=True))
    # Book value just before the addition: 10,000 - 6*333.33 = 8,000.02;
    # + 1,000 addition - 1,000 salvage = new_total = 8,000.02, over 6
    # remaining installments, recomputed at 40%/year on THIS new base.
    assert sum(amounts, Decimal("0")) == Decimal("8000.02")
    assert amounts[0] != Decimal("1000.00")  # not a plain straight-line carry-over


def test_tenant_isolation(tenant_a, tenant_b, owner_client, user_b):
    entity = _entity(tenant_a)
    asset = _asset_with_running_schedule(tenant_a, entity, owner_client)
    generate_due_installments(tenant=tenant_a, as_of=date(2026, 6, 30))

    other_client = _client(user_b)
    response = other_client.post(
        f"/api/assets/{asset.id}/additions/", {"date": "2026-06-20", "amount_base": "1000.00"}, format="json",
    )
    assert response.status_code == 404, response.data
