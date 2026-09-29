"""Sprint 6.5 (block 6.5.2, decision 5-متناقص): declining-balance
depreciation, recomputed per fiscal year on the book value at that
year's own start — including the partial-first-year convention (the
monthly share is always the year's charge ÷ 12, never ÷ the months
actually in the schedule that year) and the schedule's own final
installment always absorbing whatever book value remains above
salvage_base exactly, since pure declining-balance math never itself
reaches salvage_base in finite time. Real HTTP API + real Postgres
throughout (§11)."""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounting.models import RecurringEntry
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


@pytest.fixture
def owner_client(user_a):
    return _client(user_a)


def _amounts(entry_id):
    entry = RecurringEntry.objects.get(id=entry_id)
    return list(entry.installments.order_by("seq").values_list("amount_base", flat=True)), entry


def test_declining_balance_recomputed_per_fiscal_year(tenant_a, owner_client):
    entity = _entity(tenant_a)
    asset = AssetFactory(
        tenant=tenant_a, legal_entity=entity, purchase_date="2026-01-01", purchase_cost="10000.00",
        salvage_value="1000.00", useful_life_months=36, depreciation_method=Asset.DepreciationMethod.DECLINING_BALANCE,
        declining_balance_rate="40",
    )
    response = _start(owner_client, asset.id)
    assert response.status_code == 201, response.data
    amounts, entry = _amounts(response.data["depreciation_schedule_id"])

    assert len(amounts) == 36
    # Year 1: 40% x 10,000 = 4,000 / 12 = 333.33, remainder on month 12.
    assert amounts[0:11] == [Decimal("333.33")] * 11
    assert amounts[11] == Decimal("333.37")
    assert sum(amounts[0:12], Decimal("0")) == Decimal("4000.00")
    # Year 2: book value 6,000 -> 40% x 6,000 = 2,400 / 12 = 200.00 exactly.
    assert amounts[12:24] == [Decimal("200.00")] * 12
    # Year 3: book value 3,600 -> 120.00/month for months 25-35, and the
    # schedule's own final installment (month 36) is overridden to the
    # true-up: book value before it is 3,600 - 1,320 = 2,280, so
    # 2,280 - 1,000 (salvage) = 1,280.
    assert amounts[24:35] == [Decimal("120.00")] * 11
    assert amounts[35] == Decimal("1280.00")

    assert sum(amounts, Decimal("0")) == Decimal("9000.00")
    total_charged = Decimal("10000.00") - sum(amounts, Decimal("0"))
    assert total_charged == Decimal("1000.00")  # ends exactly at salvage_value


def test_36_month_schedule_due_dates_are_all_true_calendar_month_ends(tenant_a, owner_client):
    """Sprint 6.5.15 (UAT item 3): the exact live "fatma" bug — a 36-
    month schedule starting 2026-08-01 needs fiscal years 2027/2028/
    2029 auto-created (apps.accounting.periods.
    create_next_fiscal_year_for_tenant), crossing 2028's leap-year
    boundary. Every installment's due_date must be the true calendar
    month-end of (start month + seq - 1) — never a day-count drift
    (the old bug's exact symptom: 2028-12-30, 2029-01-30, 02-27, ...
    instead of 12-31, 01-31, 02-28, ...)."""
    import calendar
    from datetime import date

    entity = _entity(tenant_a)
    asset = AssetFactory(
        tenant=tenant_a, legal_entity=entity, purchase_date="2026-08-01", purchase_cost="10000.00",
        salvage_value="1000.00", useful_life_months=36, depreciation_method=Asset.DepreciationMethod.DECLINING_BALANCE,
        declining_balance_rate="40",
    )
    response = _start(owner_client, asset.id)
    assert response.status_code == 201, response.data
    entry = RecurringEntry.objects.get(id=response.data["depreciation_schedule_id"])
    due_dates = list(entry.installments.order_by("seq").values_list("due_date", flat=True))

    assert len(due_dates) == 36
    for seq, due_date in enumerate(due_dates, start=1):
        month_index = (8 - 1 + seq - 1)  # August 2026 is month 0 of the schedule
        year = 2026 + month_index // 12
        month = month_index % 12 + 1
        expected = date(year, month, calendar.monthrange(year, month)[1])
        assert due_date == expected, f"seq {seq}: expected {expected}, got {due_date}"

    # The exact dates the live bug reported, confirmed correct here.
    assert due_dates[28] == date(2028, 12, 31)  # seq 29
    assert due_dates[29] == date(2029, 1, 31)  # seq 30
    assert due_dates[35] == date(2029, 7, 31)  # seq 36


def test_partial_first_year_same_monthly_amount_then_recomputes_in_january(tenant_a, owner_client):
    entity = _entity(tenant_a)
    asset = AssetFactory(
        tenant=tenant_a, legal_entity=entity, purchase_date="2026-10-01", purchase_cost="12000.00",
        salvage_value="0", useful_life_months=15, depreciation_method=Asset.DepreciationMethod.DECLINING_BALANCE,
        declining_balance_rate="40",
    )
    response = _start(owner_client, asset.id)
    assert response.status_code == 201, response.data
    amounts, entry = _amounts(response.data["depreciation_schedule_id"])

    assert len(amounts) == 15
    # Partial first year (Oct-Dec 2026, 3 months): 40% x 12,000 = 4,800
    # / 12 = 400.00 — the SAME monthly amount for all 3, not 4,800/3.
    assert amounts[0:3] == [Decimal("400.00")] * 3
    # 2027 (a full 12-month year, months 4-15): book value 12,000 -
    # 1,200 = 10,800 -> 40% x 10,800 = 4,320 / 12 = 360.00, except the
    # schedule's own final (15th) installment, overridden to the
    # true-up: book value before it = 10,800 - 360*11 = 6,840 -> 6,840.
    assert amounts[3:14] == [Decimal("360.00")] * 11
    assert amounts[14] == Decimal("6840.00")
    assert sum(amounts, Decimal("0")) == Decimal("12000.00")


def test_rate_must_be_strictly_between_0_and_100(tenant_a, owner_client):
    entity = _entity(tenant_a)
    zero_rate = AssetFactory(
        tenant=tenant_a, legal_entity=entity, purchase_date="2026-01-01", purchase_cost="10000.00",
        useful_life_months=12, depreciation_method=Asset.DepreciationMethod.DECLINING_BALANCE,
        declining_balance_rate="0",
    )
    assert _start(owner_client, zero_rate.id).status_code == 400

    over_rate = AssetFactory(
        tenant=tenant_a, legal_entity=entity, purchase_date="2026-01-01", purchase_cost="10000.00",
        useful_life_months=12, depreciation_method=Asset.DepreciationMethod.DECLINING_BALANCE,
        declining_balance_rate="100",
    )
    assert _start(owner_client, over_rate.id).status_code == 400


def test_book_value_never_drops_below_salvage_and_schedule_shortens_early(tenant_a, owner_client):
    # An aggressive 99% rate against a slim 100-wide depreciable band
    # (1,000 - 900 salvage) exhausts the asset in 2 months even though
    # 3 were nominally reserved — the floor check must clip the 2nd
    # installment to exactly the remaining margin and never generate a
    # 3rd at all, shrinking installments_count to match reality.
    entity = _entity(tenant_a)
    asset = AssetFactory(
        tenant=tenant_a, legal_entity=entity, purchase_date="2026-01-01", purchase_cost="1000.00",
        salvage_value="900.00", useful_life_months=3, depreciation_method=Asset.DepreciationMethod.DECLINING_BALANCE,
        declining_balance_rate="99",
    )
    response = _start(owner_client, asset.id)
    assert response.status_code == 201, response.data
    amounts, entry = _amounts(response.data["depreciation_schedule_id"])

    assert entry.installments_count == len(amounts)
    assert len(amounts) < 3
    assert sum(amounts, Decimal("0")) == Decimal("100.00")
    for i in range(len(amounts) - 1):
        # every non-final installment strictly respects the floor too
        assert amounts[i] > Decimal("0")


def test_tenant_isolation(tenant_a, tenant_b, owner_client, user_b):
    entity = _entity(tenant_a)
    asset = AssetFactory(
        tenant=tenant_a, legal_entity=entity, purchase_date="2026-01-01", purchase_cost="10000.00",
        salvage_value="1000.00", useful_life_months=36, depreciation_method=Asset.DepreciationMethod.DECLINING_BALANCE,
        declining_balance_rate="40",
    )
    started = _start(owner_client, asset.id)
    assert started.status_code == 201, started.data
    schedule_id = started.data["depreciation_schedule_id"]

    other_client = _client(user_b)
    response = other_client.get(f"/api/depreciation-schedules/{schedule_id}/")
    assert response.status_code == 404, response.data
