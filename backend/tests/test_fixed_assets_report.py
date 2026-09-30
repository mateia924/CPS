"""Sprint 6.5 (block 6.5.5, decision 13): GET /api/reports/fixed-assets/
— per-asset register rows plus the reconciliation footer (the same
apps.assets.reconciliation.register_vs_ledger the period-close
checklist's own WARN reads). Real HTTP API + real Postgres throughout
(§11)."""

from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounting.models import Account
from apps.accounting.recurring import generate_due_installments
from apps.accounting.services import (
    create_manual_journal_entry,
    post_journal_entry,
    submit_journal_entry_for_approval,
)
from apps.organization.models import LegalEntity

from .factories import AssetFactory, LegalEntityFactory


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def owner_client(user_a):
    return _client(user_a)


@pytest.fixture
def company(tenant_a):
    return LegalEntity.objects.get(tenant=tenant_a, code="MAIN")


@pytest.fixture
def branch_a(tenant_a):
    return LegalEntity.objects.get(tenant=tenant_a, code="MAIN-01")


def _cash_account(tenant):
    return Account.objects.get(tenant=tenant, system_key="CASH")


def _post_purchase_jv(tenant, user, entity, cost, on_date=date(2026, 1, 1)):
    fixed_assets = Account.objects.get(tenant=tenant, system_key="FIXED_ASSETS")
    cash = _cash_account(tenant)
    entry = create_manual_journal_entry(
        tenant=tenant, user=user, legal_entity=entity, date=on_date,
        line_specs=[
            {"account": fixed_assets, "debit_fc": cost, "credit_fc": Decimal("0")},
            {"account": cash, "debit_fc": Decimal("0"), "credit_fc": cost},
        ],
        currency="SAR", exchange_rate=Decimal("1"), override_reason="شراء أصل ثابت",
    )
    submit_journal_entry_for_approval(entry, user)
    post_journal_entry(entry, user)
    return entry


def test_clean_scenario_reconciles_with_zero_diff(tenant_a, owner_client, user_a, branch_a):
    asset = AssetFactory(
        tenant=tenant_a, legal_entity=branch_a, purchase_date="2026-01-01", purchase_cost="10000.00",
        salvage_value="0", useful_life_months=10,
    )
    _post_purchase_jv(tenant_a, user_a, branch_a, Decimal("10000.00"))
    started = owner_client.post(f"/api/assets/{asset.id}/start-depreciation/")
    assert started.status_code == 201, started.data

    response = owner_client.get("/api/reports/fixed-assets/")
    assert response.status_code == 200, response.data
    assert response.data["reconciliation"]["cost_diff"] == "0.00"
    assert response.data["reconciliation"]["accum_diff"] == "0.00"
    row = next(r for r in response.data["rows"] if r["asset_id"] == str(asset.id))
    assert row["code"] == asset.code
    assert row["cost"] == "10000.00"
    assert row["remaining_months"] == 10


def test_manual_override_on_fixed_assets_shows_up_as_a_diff(tenant_a, owner_client, user_a, branch_a):
    asset = AssetFactory(
        tenant=tenant_a, legal_entity=branch_a, purchase_date="2026-01-01", purchase_cost="10000.00",
        salvage_value="0", useful_life_months=10,
    )
    _post_purchase_jv(tenant_a, user_a, branch_a, Decimal("10000.00"))
    started = owner_client.post(f"/api/assets/{asset.id}/start-depreciation/")
    assert started.status_code == 201, started.data

    # An unrelated manual override JV directly on FIXED_ASSETS — the
    # register (still just this one asset's cost_base) doesn't know
    # about it, so the ledger and register must now disagree.
    _post_purchase_jv(tenant_a, user_a, branch_a, Decimal("500.00"), on_date=date(2026, 2, 1))

    response = owner_client.get("/api/reports/fixed-assets/")
    assert response.status_code == 200, response.data
    assert response.data["reconciliation"]["cost_diff"] != "0.00"


def test_include_children_false_excludes_the_branch(tenant_a, owner_client, user_a, company, branch_a):
    asset = AssetFactory(
        tenant=tenant_a, legal_entity=branch_a, purchase_date="2026-01-01", purchase_cost="10000.00",
        salvage_value="0", useful_life_months=10,
    )
    response = owner_client.get(f"/api/reports/fixed-assets/?legal_entity={company.id}&include_children=false")
    assert response.status_code == 200, response.data
    assert all(row["asset_id"] != str(asset.id) for row in response.data["rows"])

    response_with_children = owner_client.get(
        f"/api/reports/fixed-assets/?legal_entity={company.id}&include_children=true"
    )
    assert any(row["asset_id"] == str(asset.id) for row in response_with_children.data["rows"])


def test_asset_disposed_within_the_requested_fiscal_year_still_shows_as_a_row(
    tenant_a, owner_client, user_a, branch_a
):
    """Sprint 6.5.18 (UAT item 4): a fully DISPOSED asset contributes
    nothing to register_totals (matching the ledger, which fully
    removed its cost/accumulated depreciation at disposal), but a
    disposal that happened during the fiscal year covering `as_of`
    must still appear as its own row — cost/additions/disposals/
    accumulated as of the disposal, book value 0 — without breaking
    the grand totals' own reconciliation against the ledger."""
    asset = AssetFactory(
        tenant=tenant_a, legal_entity=branch_a, purchase_date="2026-01-01", purchase_cost="10000.00",
        salvage_value="0", useful_life_months=10,
    )
    _post_purchase_jv(tenant_a, user_a, branch_a, Decimal("10000.00"))
    started = owner_client.post(f"/api/assets/{asset.id}/start-depreciation/")
    assert started.status_code == 201, started.data
    generate_due_installments(tenant=tenant_a, as_of=date(2026, 3, 1))

    disposed = owner_client.post(
        f"/api/assets/{asset.id}/dispose/", {"date": "2026-03-15", "fraction": "1"}, format="json",
    )
    assert disposed.status_code == 201, disposed.data

    response = owner_client.get("/api/reports/fixed-assets/?as_of=2026-12-31")
    assert response.status_code == 200, response.data
    # Grand totals must not have picked the disposed asset back up —
    # the reconciliation against the ledger (which no longer carries
    # this asset's cost/accumulated at all) must still be clean.
    assert response.data["reconciliation"]["cost_diff"] == "0.00"
    assert response.data["reconciliation"]["accum_diff"] == "0.00"

    row = next(r for r in response.data["rows"] if r["asset_id"] == str(asset.id))
    assert row["status"] == "disposed"
    assert row["cost"] == "10000.00"
    assert row["disposals"] == "10000.00"
    assert row["book_value"] == "0.00"
    assert Decimal(row["accumulated_depreciation"]) > Decimal("0")

    # A disposal from a PRIOR fiscal year must not resurface either.
    early_response = owner_client.get("/api/reports/fixed-assets/?as_of=2025-12-31")
    assert early_response.status_code == 200, early_response.data
    assert all(r["asset_id"] != str(asset.id) for r in early_response.data["rows"])


def test_tenant_isolation(tenant_a, tenant_b, owner_client, user_b):
    entity_b = LegalEntityFactory(tenant=tenant_b)
    asset_b = AssetFactory(
        tenant=tenant_b, legal_entity=entity_b, purchase_date="2026-01-01", purchase_cost="1000.00",
    )
    response = owner_client.get("/api/reports/fixed-assets/")
    assert response.status_code == 200, response.data
    assert all(row["asset_id"] != str(asset_b.id) for row in response.data["rows"])
