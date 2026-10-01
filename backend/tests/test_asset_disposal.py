"""Sprint 6.5 (block 6.5.4, decision 7): full and partial asset
disposal — cumulative fractions, computed gain/loss on
DISPOSAL_GAIN_LOSS, and the sprint's own literal acceptance scenario
(start → addition → partial disposal → full disposal, register =
ledger at every step). Real HTTP API + real Postgres throughout (§11)."""

from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounting.models import Account, JournalEntry, RecurringInstallment
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
    # Sprint 6.5.18 (UAT item 9): Decimal.normalize() on an exact power
    # of ten (100% here) used to render as "1E+2%" — the live bug on
    # Fatma's own 30%/70% disposals.
    assert "100%" in entry.memo
    assert "E+" not in entry.memo
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

    # Sprint 6.5.18 (UAT item 9): the exact live bug — 30% used to
    # render as "3E+1%" in this same memo.
    entry = JournalEntry.objects.get(id=response.data["journal_entry"])
    assert "30%" in entry.memo
    assert "E+" not in entry.memo

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


def test_historical_installments_survive_disposal_reschedule_and_full_disposal(tenant_a, owner_client):
    """Sprint 6.5.18 (items 3, 9): the 8 installments generated on the
    schedule active before a partial disposal must stay visible (with
    their own journal_entry links) after the disposal reschedules the
    remainder onto a brand-new RecurringEntry — and must still be
    visible, unchanged, after a second, full disposal sends
    Asset.depreciation_entry back to null entirely."""
    entity = _entity(tenant_a)
    asset = _asset_with_running_schedule(tenant_a, entity, owner_client)
    generate_due_installments(tenant=tenant_a, as_of=date(2026, 8, 31))
    old_entry_id = asset.depreciation_entry_id

    first = owner_client.post(
        f"/api/assets/{asset.id}/dispose/", {"date": "2026-09-15", "fraction": "0.3"}, format="json",
    )
    assert first.status_code == 201, first.data

    detail = owner_client.get(f"/api/assets/{asset.id}/")
    history = detail.data["historical_installments"]
    assert len(history) == 8
    assert {row["seq"] for row in history} == set(range(1, 9))
    assert all(row["journal_entry"] is not None for row in history)

    second = owner_client.post(
        f"/api/assets/{asset.id}/dispose/", {"date": "2026-09-20", "fraction": "0.7"}, format="json",
    )
    assert second.status_code == 201, second.data
    asset.refresh_from_db()
    assert asset.status == Asset.Status.DISPOSED
    assert asset.depreciation_entry_id is None

    detail2 = owner_client.get(f"/api/assets/{asset.id}/")
    history2 = detail2.data["historical_installments"]
    assert len(history2) == 8  # the new entry from the first disposal never generated any
    assert {row["seq"] for row in history2} == set(range(1, 9))
    assert not RecurringInstallment.objects.filter(entry_id=old_entry_id, status="due").exists()


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


def test_cumulative_disposal_accum_share_uses_original_asset_basis_not_previous_fraction(tenant_a, owner_client, user_a):
    """Sprint 6.5.18 (UAT diagnosis on tenant "fatma"): a second,
    cumulative disposal left 1750 at a real 2,814 credit instead of 0
    — dispose_asset() mixed scales, subtracting the REMAINING slice's
    book value from the FULL original cost_base to get accum_total,
    then applying the NEW disposal's original-relative fraction to
    that mismatched figure. The exact scenario from the ticket: 0.3
    disposed for 3,000 proceeds, then the remaining 0.7 for 11,000, on
    an asset with cost 14,400 and 1,000 pre-existing accumulated
    depreciation, no schedule ever started (so accum never changes
    except via the disposals themselves)."""
    entity = _entity(tenant_a)
    asset = AssetFactory(
        tenant=tenant_a, legal_entity=entity, purchase_date="2026-01-01", purchase_cost="14400.00",
        salvage_value="0", useful_life_months=12, opening_accumulated_depreciation="1000.00",
        # current_book_value()'s opening_accumulated_depreciation branch
        # only applies once cost_base is frozen (normally done by
        # start-depreciation) — set directly here since this scenario
        # deliberately never starts a schedule at all.
        cost_base="14400.00", salvage_base="0.00",
    )
    fixed_assets = Account.objects.get(tenant=tenant_a, system_key="FIXED_ASSETS")
    accum = Account.objects.get(tenant=tenant_a, system_key="ACCUM_DEPRECIATION")
    opening_balance = Account.objects.get(tenant=tenant_a, system_key="OPENING_BALANCE")
    entry = create_manual_journal_entry(
        tenant=tenant_a, user=user_a, legal_entity=entity, date=date(2026, 1, 1),
        line_specs=[
            {"account": fixed_assets, "debit_fc": Decimal("14400.00"), "credit_fc": Decimal("0")},
            {"account": accum, "debit_fc": Decimal("0"), "credit_fc": Decimal("1000.00")},
            {"account": opening_balance, "debit_fc": Decimal("0"), "credit_fc": Decimal("13400.00")},
        ],
        currency="SAR", exchange_rate=Decimal("1"), override_reason="رصيد افتتاحي للأصل",
    )
    submit_journal_entry_for_approval(entry, user_a)
    post_journal_entry(entry, user_a)

    cash = _cash_account(tenant_a)
    first = owner_client.post(
        f"/api/assets/{asset.id}/dispose/",
        {"date": "2026-09-26", "fraction": "0.3", "proceeds_base": "3000.00", "proceeds_account": str(cash.id)},
        format="json",
    )
    assert first.status_code == 201, first.data
    assert first.data["cost_share"] == "4320.00"
    assert first.data["accum_share"] == "300.00"
    assert Decimal(first.data["gain_loss"]) == Decimal("-1020.00")  # a loss

    second = owner_client.post(
        f"/api/assets/{asset.id}/dispose/",
        {"date": "2026-09-30", "fraction": "0.7", "proceeds_base": "11000.00", "proceeds_account": str(cash.id)},
        format="json",
    )
    assert second.status_code == 201, second.data
    assert second.data["cost_share"] == "10080.00"
    assert second.data["accum_share"] == "700.00"  # not 3,514.00 — the exact live bug
    assert Decimal(second.data["gain_loss"]) == Decimal("1620.00")  # a gain

    asset.refresh_from_db()
    assert asset.status == Asset.Status.DISPOSED

    fixed_assets_lines = fixed_assets.journal_lines.filter(entry__tenant=tenant_a, entry__status="posted")
    accum_lines = accum.journal_lines.filter(entry__tenant=tenant_a, entry__status="posted")
    gain_loss = Account.objects.get(tenant=tenant_a, system_key="DISPOSAL_GAIN_LOSS")
    gain_loss_lines = gain_loss.journal_lines.filter(entry__tenant=tenant_a, entry__status="posted")

    fixed_assets_balance = sum(
        (line.debit - line.credit for line in fixed_assets_lines), Decimal("0")
    )
    accum_balance = sum((line.debit - line.credit for line in accum_lines), Decimal("0"))
    gain_loss_net = sum((line.credit - line.debit for line in gain_loss_lines), Decimal("0"))

    assert fixed_assets_balance == Decimal("0.00")
    assert accum_balance == Decimal("0.00")
    assert gain_loss_net == Decimal("600.00")  # net credit (gain) across both disposals


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


def test_delete_draft_disposal_soft_deletes(tenant_a, owner_client, user_a):
    """Sprint 6.6.5: `dispose_asset` always auto-submits immediately —
    this tenant fixture seeds no asset_disposal ApprovalRule, so every
    disposal auto-approves and posts in the same call (see the other
    tests in this file, every `dispose/` response already has a
    journal_entry). A genuinely still-DRAFT row (no rule matched yet,
    i.e. before `submit_for_approval` ever runs) is therefore only
    reachable by constructing it directly, same as this mixin's
    eligibility contract requires regardless of how it's reached."""
    from apps.assets.models import AssetDisposal

    entity = _entity(tenant_a)
    asset = _asset_with_running_schedule(tenant_a, entity, owner_client)
    disposal = AssetDisposal.objects.create(
        tenant=tenant_a, asset=asset, date=date(2026, 9, 1), fraction=Decimal("0.5"),
        cost_share=Decimal("6000.00"), accum_share=Decimal("4000.00"), gain_loss=Decimal("0"),
        created_by=user_a,
    )

    deleted = owner_client.delete(f"/api/asset-disposals/{disposal.id}/")
    assert deleted.status_code == 204, deleted.data
    disposal.refresh_from_db()
    assert disposal.deleted_at is not None
    assert owner_client.get(f"/api/asset-disposals/{disposal.id}/").status_code == 404


def test_delete_approved_disposal_returns_409(tenant_a, owner_client):
    entity = _entity(tenant_a)
    asset = _asset_with_running_schedule(tenant_a, entity, owner_client)
    generate_due_installments(tenant=tenant_a, as_of=date(2026, 8, 31))
    response = owner_client.post(
        f"/api/assets/{asset.id}/dispose/", {"date": "2026-09-15", "fraction": "1"}, format="json",
    )
    assert response.status_code == 201, response.data

    deleted = owner_client.delete(f"/api/asset-disposals/{response.data['id']}/")
    assert deleted.status_code == 409, deleted.data
