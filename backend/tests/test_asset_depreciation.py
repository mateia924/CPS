"""Sprint 6.5 (block 6.5.1, docs/SYSTEM_ANALYSIS.md 3.3/3.15.4/3.9,
decisions 3, 4, 5-straight-line, 9, 10, 11, 12, 14): starting a
straight-line depreciation schedule via the RecurringEntry engine,
the ASSET_DEPRECIATION approval channel, the reversal guard, and the
period-close checklist's two new WARN checks replacing the dead
depreciation_not_enabled INFO line. Real HTTP API + real Postgres
throughout (§11: manual testing never writes to a live tenant)."""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.access.models import Role
from apps.access.services import seed_default_roles
from apps.accounting.models import Account, FiscalPeriod, JournalEntry, RecurringEntry
from apps.accounting.period_close import period_checklist
from apps.accounting.periods import close_period
from apps.accounting.recurring import generate_due_installments
from apps.approvals.models import ApprovalRule
from apps.assets.models import Asset
from apps.reports.services import balance_sheet
from apps.treasury.models import ExchangeRate

from .factories import AssetFactory, CostCenterFactory, LegalEntityFactory, UserFactory


def _roles(tenant):
    existing = {r.name: r for r in Role.objects.filter(tenant=tenant, is_system=True)}
    return existing or seed_default_roles(tenant)


def _seed_depreciation_rule(tenant):
    owner_role = _roles(tenant)["Owner"]
    return ApprovalRule.objects.get_or_create(
        tenant=tenant, doc_type=ApprovalRule.DocType.ASSET_DEPRECIATION, min_amount=0,
        defaults={"required_role": owner_role, "is_active": True},
    )[0]


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _entity(tenant):
    return LegalEntityFactory(tenant=tenant)


def _period(tenant, seq, year="2026"):
    return FiscalPeriod.objects.get(fiscal_year__tenant=tenant, fiscal_year__name=year, seq=seq)


def _account(tenant, system_key):
    return Account.objects.get(tenant=tenant, system_key=system_key)


def _start(client, asset_id):
    return client.post(f"/api/assets/{asset_id}/start-depreciation/")


@pytest.fixture
def owner_client(user_a):
    return _client(user_a)


def test_straight_line_even_split_no_salvage(tenant_a, owner_client):
    entity = _entity(tenant_a)
    asset = AssetFactory(
        tenant=tenant_a, legal_entity=entity, purchase_date="2026-01-01", purchase_cost="12000.00",
        salvage_value="0", useful_life_months=12,
    )
    response = _start(owner_client, asset.id)
    assert response.status_code == 201, response.data
    installments = response.data.get("depreciation_schedule_id")
    assert installments is not None

    entry = RecurringEntry.objects.get(id=installments)
    assert entry.installments_count == 12
    amounts = list(entry.installments.order_by("seq").values_list("amount_base", flat=True))
    assert amounts == [Decimal("1000.00")] * 12


def test_remainder_on_last_installment(tenant_a, owner_client):
    entity = _entity(tenant_a)
    asset = AssetFactory(
        tenant=tenant_a, legal_entity=entity, purchase_date="2026-01-01", purchase_cost="10000.00",
        salvage_value="0", useful_life_months=3,
    )
    response = _start(owner_client, asset.id)
    assert response.status_code == 201, response.data

    entry = RecurringEntry.objects.get(id=response.data["depreciation_schedule_id"])
    amounts = list(entry.installments.order_by("seq").values_list("amount_base", flat=True))
    assert amounts == [Decimal("3333.33"), Decimal("3333.33"), Decimal("3333.34")]
    assert sum(amounts, Decimal("0")) == Decimal("10000.00")


def test_elapsed_months_reduce_remaining_installments(tenant_a, owner_client, user_a):
    # Decision 9: in-service month is January 2026, but periods 1-4
    # (Jan-Apr) are already closed by the time depreciation starts —
    # those 4 months "elapse" and shorten the schedule instead of
    # trying to post into a period that can no longer accept an entry.
    for seq in range(1, 5):
        close_period(_period(tenant_a, seq), user_a, acknowledge_warnings=True)

    entity = _entity(tenant_a)
    asset = AssetFactory(
        tenant=tenant_a, legal_entity=entity, purchase_date="2026-01-01", purchase_cost="10000.00",
        salvage_value="1000.00", useful_life_months=12, opening_accumulated_depreciation="3000.00",
    )
    response = _start(owner_client, asset.id)
    assert response.status_code == 201, response.data

    entry = RecurringEntry.objects.get(id=response.data["depreciation_schedule_id"])
    assert entry.installments_count == 8
    amounts = list(entry.installments.order_by("seq").values_list("amount_base", flat=True))
    assert amounts == [Decimal("750.00")] * 8
    assert entry.first_period == _period(tenant_a, 5)


def test_fully_depreciated_asset_returns_400(tenant_a, owner_client):
    entity = _entity(tenant_a)
    asset = AssetFactory(
        tenant=tenant_a, legal_entity=entity, purchase_date="2026-01-01", purchase_cost="10000.00",
        salvage_value="1000.00", useful_life_months=12, opening_accumulated_depreciation="9000.00",
    )
    response = _start(owner_client, asset.id)
    assert response.status_code == 400, response.data


def test_non_depreciable_asset_returns_400(tenant_a, owner_client):
    entity = _entity(tenant_a)
    asset = AssetFactory(
        tenant=tenant_a, legal_entity=entity, purchase_date="2026-01-01", purchase_cost="10000.00",
        useful_life_months=12, is_depreciable=False,
    )
    response = _start(owner_client, asset.id)
    assert response.status_code == 400, response.data


def test_usd_asset_freezes_cost_base_at_purchase_rate(tenant_a, owner_client):
    ExchangeRate.objects.create(tenant=tenant_a, from_currency="USD", to_currency="SAR", date="2026-01-01", rate="3.75")
    entity = _entity(tenant_a)
    asset = AssetFactory(
        tenant=tenant_a, legal_entity=entity, purchase_date="2026-01-01", purchase_cost="1000.00",
        salvage_value="0", useful_life_months=10, currency="USD",
    )
    response = _start(owner_client, asset.id)
    assert response.status_code == 201, response.data
    asset.refresh_from_db()
    assert asset.cost_base == Decimal("3750.00")


def test_declining_balance_not_supported_yet_returns_400(tenant_a, owner_client):
    entity = _entity(tenant_a)
    asset = AssetFactory(
        tenant=tenant_a, legal_entity=entity, purchase_date="2026-01-01", purchase_cost="10000.00",
        useful_life_months=12, depreciation_method=Asset.DepreciationMethod.DECLINING_BALANCE,
        declining_balance_rate="40",
    )
    response = _start(owner_client, asset.id)
    assert response.status_code == 400, response.data


def test_second_start_call_on_active_schedule_returns_409(tenant_a, owner_client):
    entity = _entity(tenant_a)
    asset = AssetFactory(
        tenant=tenant_a, legal_entity=entity, purchase_date="2026-01-01", purchase_cost="12000.00",
        salvage_value="0", useful_life_months=12,
    )
    first = _start(owner_client, asset.id)
    assert first.status_code == 201, first.data
    second = _start(owner_client, asset.id)
    assert second.status_code == 409, second.data


def test_generate_first_installment_posts_journal_entry_with_cost_center(tenant_a, owner_client):
    entity = _entity(tenant_a)
    cost_center = CostCenterFactory(tenant=tenant_a)
    asset = AssetFactory(
        tenant=tenant_a, legal_entity=entity, purchase_date="2026-01-01", purchase_cost="12000.00",
        salvage_value="0", useful_life_months=12, cost_center=cost_center,
    )
    started = _start(owner_client, asset.id)
    assert started.status_code == 201, started.data

    result = generate_due_installments(tenant=tenant_a)
    assert result["generated"] >= 1

    accum = _account(tenant_a, "ACCUM_DEPRECIATION")
    expense = _account(tenant_a, "DEPRECIATION_EXPENSE")
    # generate_due_installments (no as_of) generates every DUE
    # installment up to "today" in one call — several months' worth,
    # since the test clock is well past January 2026 — so pick the
    # first one deterministically rather than assuming there's only one.
    entry = JournalEntry.objects.filter(source_type="recurring", lines__account=expense).order_by("date").first()
    assert entry is not None
    assert entry.date == _period(tenant_a, 1).end_date
    assert entry.status == JournalEntry.Status.POSTED
    lines = {line.account_id: line for line in entry.lines.all()}
    assert lines[expense.id].debit == Decimal("1000.00")
    assert lines[expense.id].cost_center_id == cost_center.id
    assert lines[accum.id].credit == Decimal("1000.00")
    assert lines[accum.id].cost_center_id == cost_center.id


def test_reversing_depreciation_installment_returns_409(tenant_a, owner_client):
    entity = _entity(tenant_a)
    asset = AssetFactory(
        tenant=tenant_a, legal_entity=entity, purchase_date="2026-01-01", purchase_cost="12000.00",
        salvage_value="0", useful_life_months=12,
    )
    started = _start(owner_client, asset.id)
    assert started.status_code == 201, started.data
    generate_due_installments(tenant=tenant_a)

    expense = _account(tenant_a, "DEPRECIATION_EXPENSE")
    entry = JournalEntry.objects.filter(source_type="recurring", lines__account=expense).order_by("date").first()
    assert entry is not None
    response = owner_client.post(f"/api/journal-entries/{entry.id}/reverse/", {"reason": "test"}, format="json")
    assert response.status_code == 409, response.data


def test_balance_sheet_shows_accumulated_depreciation_negative_and_balances(tenant_a, owner_client):
    entity = _entity(tenant_a)
    asset = AssetFactory(
        tenant=tenant_a, legal_entity=entity, purchase_date="2026-01-01", purchase_cost="12000.00",
        salvage_value="0", useful_life_months=12,
    )
    started = _start(owner_client, asset.id)
    assert started.status_code == 201, started.data
    generate_due_installments(tenant=tenant_a)

    sheet = balance_sheet(tenant_a)
    accum = _account(tenant_a, "ACCUM_DEPRECIATION")
    row = next(r for r in sheet["assets"] if r["account_id"] == str(accum.id))
    assert row["amount"] < 0
    assert sheet["total_assets"] == sheet["total_liabilities"] + sheet["total_equity"]


def test_due_installment_not_generated_blocks_period_close(tenant_a, owner_client):
    entity = _entity(tenant_a)
    asset = AssetFactory(
        tenant=tenant_a, legal_entity=entity, purchase_date="2026-01-01", purchase_cost="12000.00",
        salvage_value="0", useful_life_months=12,
    )
    started = _start(owner_client, asset.id)
    assert started.status_code == 201, started.data
    # Not generated yet — the installment for period 1 is DUE.
    checklist = period_checklist(_period(tenant_a, 1))
    codes = [item["code"] for item in checklist]
    assert "recurring_installments_due" in codes
    blocks = [item for item in checklist if item["level"] == "block"]
    assert any(item["code"] == "recurring_installments_due" for item in blocks)


def test_depreciable_asset_without_schedule_warns_at_period_close(tenant_a):
    entity = _entity(tenant_a)
    AssetFactory(
        tenant=tenant_a, legal_entity=entity, purchase_date="2026-01-01", purchase_cost="12000.00",
        salvage_value="0", useful_life_months=12,
    )
    checklist = period_checklist(_period(tenant_a, 1))
    warn = next(item for item in checklist if item["code"] == "depreciable_assets_without_schedule")
    assert warn["level"] == "warn"


def test_depreciation_not_enabled_info_removed(tenant_a):
    checklist = period_checklist(_period(tenant_a, 1))
    codes = [item["code"] for item in checklist]
    assert "depreciation_not_enabled" not in codes


def test_creator_cannot_approve_own_schedule_outside_single_user_mode(tenant_a, user_a):
    _seed_depreciation_rule(tenant_a)
    UserFactory(tenant=tenant_a, email="second-owner@depreciation.test").roles.add(_roles(tenant_a)["Owner"])
    client = _client(user_a)
    entity = _entity(tenant_a)
    asset = AssetFactory(
        tenant=tenant_a, legal_entity=entity, purchase_date="2026-01-01", purchase_cost="12000.00",
        salvage_value="0", useful_life_months=12,
    )
    started = _start(client, asset.id)
    assert started.status_code == 201, started.data
    schedule_id = started.data["depreciation_schedule_id"]
    # A rule now matches (min_amount=0), so start-depreciation only
    # submits — it does not auto-approve — and the creator may not
    # approve their own schedule in a multi-user tenant.

    entry = RecurringEntry.objects.get(id=schedule_id)
    assert entry.status == "pending_approval"
    response = client.post(f"/api/depreciation-schedules/{schedule_id}/approve/")
    assert response.status_code == 403, response.data


def test_tenant_isolation(tenant_a, tenant_b, owner_client, user_b):
    entity = _entity(tenant_a)
    asset = AssetFactory(
        tenant=tenant_a, legal_entity=entity, purchase_date="2026-01-01", purchase_cost="12000.00",
        salvage_value="0", useful_life_months=12,
    )
    started = _start(owner_client, asset.id)
    assert started.status_code == 201, started.data
    schedule_id = started.data["depreciation_schedule_id"]

    other_client = _client(user_b)
    response = other_client.get(f"/api/depreciation-schedules/{schedule_id}/")
    assert response.status_code == 404, response.data
