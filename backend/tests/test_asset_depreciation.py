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

from apps.access.models import Role, UserEntityAccess
from apps.access.services import seed_default_roles
from apps.accounting.models import Account, FiscalPeriod, JournalEntry, RecurringEntry
from apps.accounting.period_close import period_checklist
from apps.accounting.periods import close_period
from apps.accounting.recurring import generate_due_installments
from apps.approvals.models import ApprovalRule
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


def test_withdraw_cancels_schedule_and_frees_asset_for_a_fresh_start(tenant_a, user_a):
    """Sprint 6.5.8 (UAT bugfix): the generic engine's withdraw() alone
    only takes a schedule PENDING_APPROVAL -> DRAFT, which used to be a
    dead end here (no edit form, and DRAFT still counts as "active" for
    start_depreciation's own 409 check) — apps.assets.depreciation.
    withdraw_depreciation_schedule now cancels it and detaches it from
    the asset, so a second start-depreciation call (with a corrected
    opening_accumulated_depreciation) succeeds immediately."""
    _seed_depreciation_rule(tenant_a)
    UserFactory(tenant=tenant_a, email="accountant@withdraw.test").roles.add(_roles(tenant_a)["Accountant"])
    client = _client(user_a)
    entity = _entity(tenant_a)
    asset = AssetFactory(
        tenant=tenant_a, legal_entity=entity, purchase_date="2026-01-01", purchase_cost="12000.00",
        salvage_value="0", useful_life_months=12, opening_accumulated_depreciation="1000.00",
    )
    started = _start(client, asset.id)
    assert started.status_code == 201, started.data
    schedule_id = started.data["depreciation_schedule_id"]
    entry = RecurringEntry.objects.get(id=schedule_id)
    assert entry.status == "pending_approval"

    withdrawn = client.post(f"/api/depreciation-schedules/{schedule_id}/withdraw/")
    assert withdrawn.status_code == 200, withdrawn.data
    assert withdrawn.data["status"] == "cancelled"

    asset.refresh_from_db()
    assert asset.depreciation_entry_id is None

    retry = client.patch(f"/api/assets/{asset.id}/", {"opening_accumulated_depreciation": "500.00"}, format="json")
    assert retry.status_code == 200, retry.data
    second_start = _start(client, asset.id)
    assert second_start.status_code == 201, second_start.data


def test_cancel_and_withdraw_return_409_once_an_installment_is_generated(tenant_a, owner_client):
    """Sprint 6.5.15 (UAT item 6): cancel_recurring_entry only cancels
    still-DUE installments, but _cancel_and_detach also nulls
    Asset.depreciation_entry — once real depreciation has posted,
    cancelling would silently orphan that history and let a second
    start-depreciation call double-count. Only disposal is the correct
    correction path from here on."""
    entity = _entity(tenant_a)
    asset = AssetFactory(
        tenant=tenant_a, legal_entity=entity, purchase_date="2026-01-01", purchase_cost="12000.00",
        salvage_value="0", useful_life_months=12,
    )
    started = _start(owner_client, asset.id)
    assert started.status_code == 201, started.data
    schedule_id = started.data["depreciation_schedule_id"]

    result = generate_due_installments(tenant=tenant_a)
    assert result["generated"] >= 1

    cancelled = owner_client.post(f"/api/depreciation-schedules/{schedule_id}/cancel/")
    assert cancelled.status_code == 409, cancelled.data

    # withdraw() can never actually reach this guard in practice — the
    # generic approvals engine's own precondition (PENDING_APPROVAL
    # only) already blocks it on an APPROVED entry with a 400 before
    # _cancel_and_detach is ever reached; installments only exist once
    # a schedule is APPROVED and activated. The guard in
    # _cancel_and_detach still covers it defensively since both
    # cancel_depreciation_schedule and withdraw_depreciation_schedule
    # share that one function.
    withdrawn = owner_client.post(f"/api/depreciation-schedules/{schedule_id}/withdraw/")
    assert withdrawn.status_code == 400, withdrawn.data

    # Untouched — still the asset's real, active schedule.
    asset.refresh_from_db()
    assert str(asset.depreciation_entry_id) == schedule_id


def test_schedule_gets_a_real_number_not_stuck_on_draft(tenant_a, owner_client):
    """Sprint 6.5.15 (UAT item 7): start_depreciation/submit_depreciation_
    schedule/add_to_asset all called submit_for_approval directly,
    unlike apps.accounting.recurring.submit_recurring_entry — entry.
    number stayed permanently blank, so the schedule detail page's
    title always showed "(مسودة)" regardless of real status."""
    entity = _entity(tenant_a)
    asset = AssetFactory(
        tenant=tenant_a, legal_entity=entity, purchase_date="2026-01-01", purchase_cost="12000.00",
        salvage_value="0", useful_life_months=12,
    )
    started = _start(owner_client, asset.id)
    assert started.status_code == 201, started.data
    entry = RecurringEntry.objects.get(id=started.data["depreciation_schedule_id"])
    assert entry.status == "approved"
    assert entry.number
    assert entry.number.startswith("RE-")


def test_draft_schedule_after_rejection_can_be_resubmitted_or_cancelled(tenant_a, user_a):
    """Sprint 6.5.8 (UAT bugfix): reject() also leaves a schedule in
    DRAFT (unlike withdraw, deliberately not redefined — an approver's
    rejection reason may be fixable, so the creator gets a real choice:
    resubmit via `submit`, or give up via `cancel` (which, like
    withdraw, frees the asset for a fresh start-depreciation call)."""
    role = _seed_depreciation_rule(tenant_a).required_role
    UserFactory(tenant=tenant_a, email="second-owner@reject.test").roles.add(role)
    client = _client(user_a)
    entity = _entity(tenant_a)
    asset = AssetFactory(
        tenant=tenant_a, legal_entity=entity, purchase_date="2026-01-01", purchase_cost="12000.00",
        salvage_value="0", useful_life_months=12,
    )
    started = _start(client, asset.id)
    schedule_id = started.data["depreciation_schedule_id"]

    rejected = client.post(f"/api/depreciation-schedules/{schedule_id}/reject/", {"reason": "خطأ في العمر الإنتاجي"})
    assert rejected.status_code == 200, rejected.data
    assert rejected.data["status"] == "draft"

    resubmitted = client.post(f"/api/depreciation-schedules/{schedule_id}/submit/")
    assert resubmitted.status_code == 200, resubmitted.data
    assert resubmitted.data["status"] == "pending_approval"

    rejected_again = client.post(f"/api/depreciation-schedules/{schedule_id}/reject/", {"reason": "still wrong"})
    assert rejected_again.status_code == 200, rejected_again.data

    cancelled = client.post(f"/api/depreciation-schedules/{schedule_id}/cancel/")
    assert cancelled.status_code == 200, cancelled.data
    assert cancelled.data["status"] == "cancelled"

    asset.refresh_from_db()
    assert asset.depreciation_entry_id is None
    second_start = _start(client, asset.id)
    assert second_start.status_code == 201, second_start.data


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


def test_generate_due_now_scoped_to_this_assets_schedule_only(tenant_a, owner_client):
    """Sprint 6.5.7: the asset detail screen's "توليد المستحق الآن"
    button must never touch another asset's due installments — only
    generate_due_installments(recurring_entry=...) for this one."""
    entity = _entity(tenant_a)
    asset_a = AssetFactory(
        tenant=tenant_a, legal_entity=entity, purchase_date="2026-01-01", purchase_cost="12000.00",
        salvage_value="0", useful_life_months=12,
    )
    asset_b = AssetFactory(
        tenant=tenant_a, legal_entity=entity, purchase_date="2026-01-01", purchase_cost="6000.00",
        salvage_value="0", useful_life_months=12,
    )
    assert _start(owner_client, asset_a.id).status_code == 201
    assert _start(owner_client, asset_b.id).status_code == 201

    response = owner_client.post(f"/api/assets/{asset_a.id}/generate-due-now/")
    assert response.status_code == 200, response.data
    assert response.data["generated"] >= 1

    asset_a.refresh_from_db()
    asset_b.refresh_from_db()
    a_installments = list(asset_a.depreciation_entry.installments.values_list("status", flat=True))
    b_installments = list(asset_b.depreciation_entry.installments.values_list("status", flat=True))
    assert "generated" in a_installments
    assert all(status == "due" for status in b_installments)


def test_generate_due_now_without_active_schedule_returns_409(tenant_a, owner_client):
    entity = _entity(tenant_a)
    asset = AssetFactory(
        tenant=tenant_a, legal_entity=entity, purchase_date="2026-01-01", purchase_cost="12000.00",
        salvage_value="0", useful_life_months=12,
    )
    response = owner_client.post(f"/api/assets/{asset.id}/generate-due-now/")
    assert response.status_code == 409, response.data


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


def test_owner_can_emergency_approve_own_schedule_when_no_other_owner_holds_role(tenant_a, user_a):
    """Sprint 6.5.8 (UAT bugfix): the asset detail screen's approve
    button now retries with emergency_reason on this exact failure —
    proving the API path it depends on actually behaves as expected:
    blocked-but-emergency-eligible -> 400 without a reason, 200 with
    one, logged as asset_depreciation.approved/is_emergency_approval."""
    _seed_depreciation_rule(tenant_a)
    UserFactory(tenant=tenant_a, email="accountant@depreciation.test").roles.add(_roles(tenant_a)["Accountant"])
    client = _client(user_a)
    entity = _entity(tenant_a)
    asset = AssetFactory(
        tenant=tenant_a, legal_entity=entity, purchase_date="2026-01-01", purchase_cost="12000.00",
        salvage_value="0", useful_life_months=12,
    )
    started = _start(client, asset.id)
    assert started.status_code == 201, started.data
    schedule_id = started.data["depreciation_schedule_id"]
    entry = RecurringEntry.objects.get(id=schedule_id)
    assert entry.status == "pending_approval"

    without_reason = client.post(f"/api/depreciation-schedules/{schedule_id}/approve/")
    assert without_reason.status_code == 400, without_reason.data

    with_reason = client.post(
        f"/api/depreciation-schedules/{schedule_id}/approve/",
        {"emergency_reason": "no accountant available"},
        format="json",
    )
    assert with_reason.status_code == 200, with_reason.data
    entry.refresh_from_db()
    assert entry.status == "approved"

    from apps.platform.models import AuditLog

    log = AuditLog.objects.filter(target_id=entry.id, action="asset_depreciation.approved").order_by("-created_at").first()
    assert log is not None
    assert log.after["is_emergency_approval"] is True


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


def test_entity_restricted_user_cannot_see_or_approve_other_entitys_schedule(tenant_a, user_a):
    """Sprint 6.5.12: DepreciationScheduleViewSet.get_queryset() now
    scopes by get_accessible_entity_ids(), same mechanism as its
    sibling RecurringEntryViewSet — a user restricted to one legal
    entity (in-tenant, not the cross-tenant case above) must never
    retrieve, approve, or generate-due-now another entity's schedule."""
    entity_a = _entity(tenant_a)
    entity_b = _entity(tenant_a)
    owner_client = _client(user_a)

    asset_a = AssetFactory(
        tenant=tenant_a, legal_entity=entity_a, purchase_date="2026-01-01", purchase_cost="12000.00",
        salvage_value="0", useful_life_months=12,
    )
    asset_b = AssetFactory(
        tenant=tenant_a, legal_entity=entity_b, purchase_date="2026-01-01", purchase_cost="6000.00",
        salvage_value="0", useful_life_months=12,
    )
    started_a = _start(owner_client, asset_a.id)
    started_b = _start(owner_client, asset_b.id)
    assert started_a.status_code == 201, started_a.data
    assert started_b.status_code == 201, started_b.data
    schedule_b_id = started_b.data["depreciation_schedule_id"]

    restricted_user = UserFactory(tenant=tenant_a, email="restricted@depreciation.test")
    restricted_user.roles.add(_roles(tenant_a)["Accountant"])
    UserEntityAccess.objects.create(user=restricted_user, legal_entity=entity_a)
    restricted_client = _client(restricted_user)

    # Entity A is accessible — retrieving its own schedule works.
    schedule_a_id = started_a.data["depreciation_schedule_id"]
    own_entity = restricted_client.get(f"/api/depreciation-schedules/{schedule_a_id}/")
    assert own_entity.status_code == 200, own_entity.data

    # Entity B is not — every action on its schedule/asset 404s, never
    # a business-logic error (the row is filtered out before any
    # approve()/generate_due_installments() code runs at all).
    retrieve = restricted_client.get(f"/api/depreciation-schedules/{schedule_b_id}/")
    assert retrieve.status_code == 404, retrieve.data

    approve = restricted_client.post(f"/api/depreciation-schedules/{schedule_b_id}/approve/")
    assert approve.status_code == 404, approve.data

    generate_due = restricted_client.post(f"/api/assets/{asset_b.id}/generate-due-now/")
    assert generate_due.status_code == 404, generate_due.data
