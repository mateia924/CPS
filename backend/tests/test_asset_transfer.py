"""Sprint 6.5 (block 6.5.5, decision 8): moving an asset between cost
centers (always free) or legal entities (restricted to within one
company). No journal entry, no approval. Real HTTP API + real
Postgres throughout (§11)."""

from datetime import date

import pytest
from rest_framework.test import APIClient

from apps.accounting.models import JournalEntry
from apps.accounting.recurring import generate_due_installments
from apps.organization.models import LegalEntity

from .factories import AssetFactory, CostCenterFactory, LegalEntityFactory


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _start(client, asset_id):
    return client.post(f"/api/assets/{asset_id}/start-depreciation/")


@pytest.fixture
def owner_client(user_a):
    return _client(user_a)


@pytest.fixture
def company(tenant_a):
    return LegalEntity.objects.get(tenant=tenant_a, code="MAIN")


@pytest.fixture
def branch_a(tenant_a):
    return LegalEntity.objects.get(tenant=tenant_a, code="MAIN-01")


@pytest.fixture
def branch_b(tenant_a, company):
    return LegalEntityFactory(tenant=tenant_a, entity_type=LegalEntity.Type.BRANCH, parent=company)


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


def test_transfer_between_branches_of_same_company_keeps_generated_untouched(
    tenant_a, owner_client, branch_a, branch_b
):
    asset = _asset_with_running_schedule(tenant_a, branch_a, owner_client)
    generate_due_installments(tenant=tenant_a, as_of=date(2026, 3, 31))  # months 1-3 generated on branch_a

    response = owner_client.post(
        f"/api/assets/{asset.id}/transfer/", {"legal_entity": str(branch_b.id), "reason": "نقل تجريبي"}, format="json",
    )
    assert response.status_code == 201, response.data

    asset.refresh_from_db()
    assert asset.legal_entity_id == branch_b.id
    assert asset.depreciation_entry.legal_entity_id == branch_b.id

    # Already-generated installments' JournalEntries keep the OLD entity.
    old_entries = JournalEntry.objects.filter(source_type="recurring", legal_entity=branch_a)
    assert old_entries.count() == 3

    generate_due_installments(tenant=tenant_a, as_of=date(2026, 4, 30))  # month 4, not yet generated before
    new_entries = JournalEntry.objects.filter(source_type="recurring", legal_entity=branch_b)
    assert new_entries.count() == 1


def test_transfer_without_a_reason_returns_400_and_stores_the_reason_when_given(
    tenant_a, owner_client, branch_a, branch_b
):
    """Sprint 6.5.18 (UAT item 9): "فورم النقل ... يطلب سببًا" —
    required, and stored on the AssetTransfer row for the log."""
    asset = _asset_with_running_schedule(tenant_a, branch_a, owner_client)

    missing_reason = owner_client.post(
        f"/api/assets/{asset.id}/transfer/", {"legal_entity": str(branch_b.id)}, format="json",
    )
    assert missing_reason.status_code == 400, missing_reason.data

    response = owner_client.post(
        f"/api/assets/{asset.id}/transfer/",
        {"legal_entity": str(branch_b.id), "reason": "افتتاح فرع جديد"}, format="json",
    )
    assert response.status_code == 201, response.data
    assert response.data["reason"] == "افتتاح فرع جديد"


def test_transfer_between_companies_returns_400(tenant_a, owner_client, branch_a):
    asset = _asset_with_running_schedule(tenant_a, branch_a, owner_client)
    other_company = LegalEntityFactory(tenant=tenant_a, entity_type=LegalEntity.Type.COMPANY)

    response = owner_client.post(
        f"/api/assets/{asset.id}/transfer/", {"legal_entity": str(other_company.id), "reason": "نقل تجريبي"}, format="json",
    )
    assert response.status_code == 400, response.data


def test_cost_center_transfer_affects_next_installment(tenant_a, owner_client, branch_a):
    old_cc = CostCenterFactory(tenant=tenant_a)
    new_cc = CostCenterFactory(tenant=tenant_a)
    asset = _asset_with_running_schedule(tenant_a, branch_a, owner_client, cost_center=old_cc)
    generate_due_installments(tenant=tenant_a, as_of=date(2026, 1, 31))  # month 1 only, generated with old_cc

    response = owner_client.post(
        f"/api/assets/{asset.id}/transfer/", {"cost_center": str(new_cc.id), "reason": "نقل تجريبي"}, format="json",
    )
    assert response.status_code == 201, response.data

    generate_due_installments(tenant=tenant_a, as_of=date(2026, 2, 28))  # month 2 only, after the transfer

    from apps.accounting.models import Account

    expense = Account.objects.get(tenant=tenant_a, system_key="DEPRECIATION_EXPENSE")
    lines = expense.journal_lines.filter(entry__source_type="recurring").order_by("entry__date")
    assert lines[0].cost_center_id == old_cc.id
    assert lines[1].cost_center_id == new_cc.id


def test_transfer_of_fully_disposed_asset_returns_400(tenant_a, owner_client, branch_a):
    asset = _asset_with_running_schedule(tenant_a, branch_a, owner_client)
    disposed = owner_client.post(
        f"/api/assets/{asset.id}/dispose/", {"date": "2026-01-15", "fraction": "1"}, format="json",
    )
    assert disposed.status_code == 201, disposed.data

    other_cc = CostCenterFactory(tenant=tenant_a)
    response = owner_client.post(
        f"/api/assets/{asset.id}/transfer/", {"cost_center": str(other_cc.id), "reason": "نقل تجريبي"}, format="json",
    )
    assert response.status_code == 400, response.data


def test_tenant_isolation(tenant_a, tenant_b, owner_client, branch_a, user_b):
    asset = _asset_with_running_schedule(tenant_a, branch_a, owner_client)
    other_cc = CostCenterFactory(tenant=tenant_b)

    other_client = _client(user_b)
    response = other_client.post(
        f"/api/assets/{asset.id}/transfer/", {"cost_center": str(other_cc.id)}, format="json",
    )
    assert response.status_code == 404, response.data
