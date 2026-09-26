"""Sprint 6.5 (block 6.5.4, decision 7): full and partial asset
disposal — cumulative fractions, computed gain/loss on
DISPOSAL_GAIN_LOSS, and the sprint's own literal acceptance scenario
(start → addition → partial disposal → full disposal, register =
ledger at every step). Real HTTP API + real Postgres throughout (§11)."""

from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounting.models import Account, JournalEntry
from apps.accounting.recurring import generate_due_installments
from apps.accounting.services import (
    create_manual_journal_entry,
    post_journal_entry,
    submit_journal_entry_for_approval,
)
from apps.assets.models import Asset
from apps.assets.reconciliation import register_vs_ledger

from .factories import AssetFactory, LegalEntityFactory


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _entity(tenant):
    return LegalEntityFactory(tenant=tenant)


def _start(client, asset_id):
    return client.post(f"/api/assets/{asset_id}/start-depreciation/")


def _cash_account(tenant):
    return Account.objects.get(tenant=tenant, system_key="CASH")


def _post_purchase_jv(tenant, user, asset, cost=Decimal("12000.00"), on_date=date(2026, 1, 1)):
    """Decision 1: registering the asset (or adding to it, 6.5.3) never
    itself posts a capital entry — the purchase/addition is a manual
    JV/voucher on FIXED_ASSETS, posted separately by the accountant.
    Without this, the ledger's own FIXED_ASSETS balance would stay at
    0 forever and could never reconcile against the register."""
    fixed_assets = Account.objects.get(tenant=tenant, system_key="FIXED_ASSETS")
    cash = _cash_account(tenant)
    entry = create_manual_journal_entry(
        tenant=tenant, user=user, legal_entity=asset.legal_entity, date=on_date,
        line_specs=[
            {"account": fixed_assets, "debit_fc": cost, "credit_fc": Decimal("0")},
            {"account": cash, "debit_fc": Decimal("0"), "credit_fc": cost},
        ],
        currency="SAR", exchange_rate=Decimal("1"), override_reason="شراء أصل ثابت",
    )
    submit_journal_entry_for_approval(entry, user)
    post_journal_entry(entry, user)
    return entry


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


def test_full_disposal_with_gain(tenant_a, owner_client):
    entity = _entity(tenant_a)
    asset = _asset_with_running_schedule(tenant_a, entity, owner_client)
    generate_due_installments(tenant=tenant_a, as_of=date(2026, 8, 31))  # 8 x 1,000 -> book value 4,000

    cash = _cash_account(tenant_a)
    response = owner_client.post(
        f"/api/assets/{asset.id}/dispose/",
        {"date": "2026-09-15", "fraction": "1", "proceeds_base": "5000.00", "proceeds_account": str(cash.id)},
        format="json",
    )
    assert response.status_code == 201, response.data
    assert response.data["gain_loss"] == "1000.00"
    assert "warnings" in response.data  # decision 7: proceeds > 0 -> tax-invoice warning

    entry = JournalEntry.objects.get(id=response.data["journal_entry"])
    assert entry.status == JournalEntry.Status.POSTED
    lines = list(entry.lines.all())
    total_debit = sum((line.debit for line in lines), Decimal("0"))
    total_credit = sum((line.credit for line in lines), Decimal("0"))
    assert total_debit == total_credit

    gain_loss_account = Account.objects.get(tenant=tenant_a, system_key="DISPOSAL_GAIN_LOSS")
    gain_line = next(line for line in lines if line.account_id == gain_loss_account.id)
    assert gain_line.credit == Decimal("1000.00")

    asset.refresh_from_db()
    assert asset.status == Asset.Status.DISPOSED
    assert asset.disposed_fraction == Decimal("1.0000")
    assert asset.depreciation_entry is None


def test_partial_disposal_with_loss_and_new_schedule_for_remainder(tenant_a, owner_client):
    entity = _entity(tenant_a)
    asset = _asset_with_running_schedule(tenant_a, entity, owner_client)
    generate_due_installments(tenant=tenant_a, as_of=date(2026, 8, 31))  # book value 4,000

    cash = _cash_account(tenant_a)
    response = owner_client.post(
        f"/api/assets/{asset.id}/dispose/",
        {"date": "2026-09-15", "fraction": "0.3", "proceeds_base": "500.00", "proceeds_account": str(cash.id)},
        format="json",
    )
    assert response.status_code == 201, response.data
    # cost_share/accum_share are exactly 30% of the totals (12,000 and 8,000).
    assert response.data["cost_share"] == "3600.00"
    assert response.data["accum_share"] == "2400.00"
    book_value_share = Decimal("3600.00") - Decimal("2400.00")  # 1,200.00
    assert Decimal(response.data["gain_loss"]) == Decimal("500.00") - book_value_share  # a loss

    asset.refresh_from_db()
    assert asset.disposed_fraction == Decimal("0.3000")
    assert asset.status == Asset.Status.ACTIVE
    new_entry = asset.depreciation_entry
    assert new_entry is not None
    # Remaining book value = (12,000 - 8,000) * 0.7 = 2,800, salvage
    # stays 0, over the 4 installments (months 9-12) still DUE.
    amounts = list(new_entry.installments.order_by("seq").values_list("amount_base", flat=True))
    assert len(amounts) == 4
    assert sum(amounts, Decimal("0")) == Decimal("2800.00")


def test_disposal_fraction_sum_over_100_percent_returns_400(tenant_a, owner_client):
    entity = _entity(tenant_a)
    asset = _asset_with_running_schedule(tenant_a, entity, owner_client)
    generate_due_installments(tenant=tenant_a, as_of=date(2026, 8, 31))

    first = owner_client.post(
        f"/api/assets/{asset.id}/dispose/", {"date": "2026-09-15", "fraction": "0.7"}, format="json",
    )
    assert first.status_code == 201, first.data
    second = owner_client.post(
        f"/api/assets/{asset.id}/dispose/", {"date": "2026-09-20", "fraction": "0.4"}, format="json",
    )
    assert second.status_code == 400, second.data


def test_disposal_of_asset_that_never_started_depreciation_uses_full_cost_no_accum(tenant_a, owner_client):
    entity = _entity(tenant_a)
    asset = AssetFactory(
        tenant=tenant_a, legal_entity=entity, purchase_date="2026-01-01", purchase_cost="5000.00",
        salvage_value="0", useful_life_months=12,
    )
    response = owner_client.post(
        f"/api/assets/{asset.id}/dispose/", {"date": "2026-03-01", "fraction": "1"}, format="json",
    )
    assert response.status_code == 201, response.data
    assert response.data["cost_share"] == "5000.00"
    assert response.data["accum_share"] == "0.00"
    assert response.data["gain_loss"] == "-5000.00"  # scrapped, proceeds 0 -> full loss


def test_zero_proceeds_produces_no_proceeds_line(tenant_a, owner_client):
    entity = _entity(tenant_a)
    asset = _asset_with_running_schedule(tenant_a, entity, owner_client)
    generate_due_installments(tenant=tenant_a, as_of=date(2026, 8, 31))

    response = owner_client.post(
        f"/api/assets/{asset.id}/dispose/", {"date": "2026-09-15", "fraction": "1"}, format="json",
    )
    assert response.status_code == 201, response.data
    assert "warnings" not in response.data

    entry = JournalEntry.objects.get(id=response.data["journal_entry"])
    accounts_used = {line.account.system_key for line in entry.lines.select_related("account")}
    assert "CASH" not in accounts_used
    assert accounts_used <= {"ACCUM_DEPRECIATION", "FIXED_ASSETS", "DISPOSAL_GAIN_LOSS"}


def test_tenant_isolation(tenant_a, tenant_b, owner_client, user_b):
    entity = _entity(tenant_a)
    asset = _asset_with_running_schedule(tenant_a, entity, owner_client)
    generate_due_installments(tenant=tenant_a, as_of=date(2026, 8, 31))
    response = owner_client.post(
        f"/api/assets/{asset.id}/dispose/", {"date": "2026-09-15", "fraction": "1"}, format="json",
    )
    assert response.status_code == 201, response.data

    other_client = _client(user_b)
    detail = other_client.get(f"/api/asset-disposals/{response.data['id']}/")
    assert detail.status_code == 404, detail.data


def test_comprehensive_acceptance_scenario(tenant_a, owner_client, user_a):
    """docs/prompts/sprint-6.5.md's literal acceptance criterion:
    "إهلاك شهري صحيح لأصل بإضافة واستبعاد" — start -> addition
    mid-life -> partial disposal -> full disposal, register == ledger
    at every step, final book value == salvage_value exactly.
    """
    entity = _entity(tenant_a)
    asset = AssetFactory(
        tenant=tenant_a, legal_entity=entity, purchase_date="2026-01-01", purchase_cost="12000.00",
        salvage_value="0", useful_life_months=12,
    )
    _post_purchase_jv(tenant_a, user_a, asset)
    started = _start(owner_client, asset.id)
    assert started.status_code == 201, started.data
    asset.refresh_from_db()

    def _reconciled(as_of):
        result = register_vs_ledger(tenant_a, as_of=as_of)
        assert result["cost_diff"] == Decimal("0.00"), result
        assert result["accum_diff"] == Decimal("0.00"), result

    _reconciled(date(2026, 1, 31))

    # Step 1: 6 months generated (1-6 x 1,000) -> book value 6,000.
    generate_due_installments(tenant=tenant_a, as_of=date(2026, 6, 30))
    _reconciled(date(2026, 6, 30))

    # Step 2: addition of 2,400 mid-life -> new 6-month schedule of 1,400/mo.
    # Decision 1: the addition itself only edits the register — its own
    # capital JV, like the original purchase, is a separate manual
    # posting the accountant makes.
    addition = owner_client.post(
        f"/api/assets/{asset.id}/additions/", {"date": "2026-06-20", "amount_base": "2400.00"}, format="json",
    )
    assert addition.status_code == 201, addition.data
    _post_purchase_jv(tenant_a, user_a, asset, cost=Decimal("2400.00"), on_date=date(2026, 6, 20))
    _reconciled(date(2026, 6, 30))

    generate_due_installments(tenant=tenant_a, as_of=date(2026, 9, 30))  # 3 more x 1,400 generated
    _reconciled(date(2026, 9, 30))

    # Step 3: partial disposal (40%) of what remains.
    partial = owner_client.post(
        f"/api/assets/{asset.id}/dispose/", {"date": "2026-09-20", "fraction": "0.4"}, format="json",
    )
    assert partial.status_code == 201, partial.data
    _reconciled(date(2026, 9, 30))

    asset.refresh_from_db()
    generate_due_installments(tenant=tenant_a, as_of=date(2026, 12, 31))
    _reconciled(date(2026, 12, 31))

    # Step 4: full disposal of whatever fraction remains.
    remaining_fraction = Decimal("1") - asset.disposed_fraction
    final = owner_client.post(
        f"/api/assets/{asset.id}/dispose/",
        {"date": "2026-12-31", "fraction": str(remaining_fraction)}, format="json",
    )
    assert final.status_code == 201, final.data
    _reconciled(date(2026, 12, 31))

    asset.refresh_from_db()
    assert asset.status == Asset.Status.DISPOSED
    assert asset.disposed_fraction == Decimal("1.0000")

    # Final book value == salvage_value (0) exactly: the register's
    # own total (net of disposed_fraction) is zero for this asset.
    totals = register_vs_ledger(tenant_a, as_of=date(2026, 12, 31))
    assert totals["register_cost"] == Decimal("0.00")
    assert totals["register_accumulated_depreciation"] == Decimal("0.00")
