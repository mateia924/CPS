"""Sprint 6.3 (docs/SYSTEM_ANALYSIS.md 3.10/3.16.3, sprint-6.md decisions
5-8): opening balances — readiness report, two-stage written approval,
adjustments. Every scenario below is one of block 6.3's own required
test scenarios (sprint-6.md line 89), against the real HTTP API and
real Postgres — never a manual `manage.py shell` write against a live
tenant (docs/SYSTEM_ANALYSIS.md §11, 2026-09-24: manual testing never
writes to a live tenant; pytest against the isolated test database is
the only sanctioned write path for exercising a new service)."""

from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.access.models import Role
from apps.access.services import seed_default_roles
from apps.accounting.models import Account, JournalEntry, OpeningBalanceEntry
from apps.accounting.periods import close_period
from apps.approvals.models import ApprovalRule
from apps.platform.models import AuditLog
from apps.treasury.models import ExchangeRate

from .factories import BankFactory, LegalEntityFactory, PartyFactory, UserFactory


def _roles(tenant):
    existing = {r.name: r for r in Role.objects.filter(tenant=tenant, is_system=True)}
    return existing or seed_default_roles(tenant)


def _seed_opening_balance_rule(tenant):
    """approvals/migrations/0007 seeds this for real tenants —
    tenant_a/tenant_b (conftest.py) build a tenant directly via
    TenantFactory, bypassing every migration's RunPython, so every test
    below seeds it explicitly (same pattern as tests/test_iban_change.py's
    _seed_iban_rule)."""
    owner_role = _roles(tenant)["Owner"]
    return ApprovalRule.objects.get_or_create(
        tenant=tenant, doc_type=ApprovalRule.DocType.OPENING_BALANCE, min_amount=0,
        defaults={"required_role": owner_role, "is_active": True},
    )[0]


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _entity(tenant):
    return LegalEntityFactory(tenant=tenant)


def _acc(tenant, code):
    return Account.objects.get(tenant=tenant, code=code)


def _line(**kwargs):
    base = {"debit_fc": "0", "credit_fc": "0"}
    base.update(kwargs)
    return base


@pytest.fixture
def owner_client(tenant_a, user_a):
    """tenant_a + user_a only — a single-active-user tenant, so the
    segregation-of-duties self-approval exemption applies (used by the
    tests that want the "happy path" single-user flow)."""
    _seed_opening_balance_rule(tenant_a)
    return _client(user_a)


# ---------------------------------------------------------------------
# Line-level validation (decision 6)
# ---------------------------------------------------------------------


def test_line_on_revenue_account_rejected(tenant_a, owner_client):
    entity = _entity(tenant_a)
    response = owner_client.post(
        "/api/opening-balances/",
        {
            "legal_entity": str(entity.id), "kind": "initial",
            "lines": [_line(account=str(_acc(tenant_a, "4100").id), debit_fc="100")],
        },
        format="json",
    )
    assert response.status_code == 400, response.data


def test_control_account_direct_selection_rejected(tenant_a, owner_client):
    entity = _entity(tenant_a)
    response = owner_client.post(
        "/api/opening-balances/",
        {
            "legal_entity": str(entity.id), "kind": "initial",
            "lines": [_line(account=str(_acc(tenant_a, "1200").id), debit_fc="100")],
        },
        format="json",
    )
    assert response.status_code == 400, response.data


def test_control_account_via_party_resolves_to_sub_ledger(tenant_a, owner_client):
    entity = _entity(tenant_a)
    party = PartyFactory(tenant=tenant_a)
    response = owner_client.post(
        "/api/opening-balances/",
        {
            "legal_entity": str(entity.id), "kind": "initial",
            "lines": [
                _line(party=str(party.id), party_role="customer", debit_fc="500"),
                _line(account=str(_acc(tenant_a, "3100").id), credit_fc="500"),
            ],
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    party_line = next(line for line in response.data["lines"] if line["party"] == party.id)
    resolved = Account.objects.get(id=party_line["account"])
    assert resolved.parent.system_key == "CUSTOMERS"
    assert resolved.party_id == party.id


def test_open_items_sum_mismatch_rejected(tenant_a, owner_client):
    entity = _entity(tenant_a)
    party = PartyFactory(tenant=tenant_a)
    response = owner_client.post(
        "/api/opening-balances/",
        {
            "legal_entity": str(entity.id), "kind": "initial",
            "lines": [
                _line(
                    party=str(party.id), party_role="customer", debit_fc="1000",
                    open_items=[{"ref": "INV-1", "date": "2026-01-01", "amount_fc": "500"}],
                ),
            ],
        },
        format="json",
    )
    assert response.status_code == 400, response.data


def test_opening_balance_account_line_is_warn_not_block(tenant_a, owner_client):
    entity = _entity(tenant_a)
    response = owner_client.post(
        "/api/opening-balances/",
        {
            "legal_entity": str(entity.id), "kind": "initial",
            "lines": [
                _line(account=str(_acc(tenant_a, "1900").id), debit_fc="200"),
                _line(account=str(_acc(tenant_a, "3900").id), credit_fc="200"),
            ],
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    entry_id = response.data["id"]
    readiness = owner_client.get(f"/api/opening-balances/{entry_id}/readiness/")
    codes = [item["code"] for item in readiness.data["items"]]
    assert "opening_balance_account_used" in codes
    assert "unbalanced" not in codes
    submitted = owner_client.post(f"/api/opening-balances/{entry_id}/submit/")
    assert submitted.status_code == 200, submitted.data


def test_foreign_currency_bank_line_converts_at_opening_date_rate(tenant_a, owner_client):
    from apps.accounting.services import get_or_create_treasury_account

    entity = _entity(tenant_a)
    bank = BankFactory(tenant=tenant_a, legal_entity=entity, currency="USD")
    get_or_create_treasury_account(bank, "BANKS")
    ExchangeRate.objects.create(
        tenant=tenant_a, from_currency="USD", to_currency="SAR", date=date(2026, 1, 1), rate=Decimal("3.75"),
    )
    response = owner_client.post(
        "/api/opening-balances/",
        {
            "legal_entity": str(entity.id), "kind": "initial",
            "lines": [
                _line(account=str(bank.gl_account_id), currency="USD", debit_fc="1000"),
                _line(account=str(_acc(tenant_a, "3100").id), credit_fc="3750"),
            ],
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    bank_line = next(line for line in response.data["lines"] if line["account"] == bank.gl_account_id)
    assert Decimal(bank_line["debit_base"]) == Decimal("3750.00")
    assert Decimal(bank_line["exchange_rate"]) == Decimal("3.75000000")


# ---------------------------------------------------------------------
# Draft / readiness / submit balance gate (decisions 6-7)
# ---------------------------------------------------------------------


def test_unbalanced_draft_is_saved_and_readiness_blocks_it(tenant_a, owner_client):
    entity = _entity(tenant_a)
    response = owner_client.post(
        "/api/opening-balances/",
        {
            "legal_entity": str(entity.id), "kind": "initial",
            "lines": [_line(account=str(_acc(tenant_a, "1900").id), debit_fc="1000")],
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    entry_id = response.data["id"]
    readiness = owner_client.get(f"/api/opening-balances/{entry_id}/readiness/")
    codes = [item["code"] for item in readiness.data["items"]]
    assert "unbalanced" in codes


def test_submit_unbalanced_rejected(tenant_a, owner_client):
    entity = _entity(tenant_a)
    created = owner_client.post(
        "/api/opening-balances/",
        {
            "legal_entity": str(entity.id), "kind": "initial",
            "lines": [_line(account=str(_acc(tenant_a, "1900").id), debit_fc="1000")],
        },
        format="json",
    )
    response = owner_client.post(f"/api/opening-balances/{created.data['id']}/submit/")
    assert response.status_code == 400, response.data


def test_submit_unbalanced_error_message_has_thousands_separator(tenant_a, owner_client):
    """Sprint 6.6.6 (§6.3): the live bug was literally "الفرق
    10000.00" (no thousands separator) in this exact message —
    apps.common.formatting.format_money fixes it project-wide."""
    entity = _entity(tenant_a)
    created = owner_client.post(
        "/api/opening-balances/",
        {
            "legal_entity": str(entity.id), "kind": "initial",
            "lines": [_line(account=str(_acc(tenant_a, "1900").id), debit_fc="10000")],
        },
        format="json",
    )
    response = owner_client.post(f"/api/opening-balances/{created.data['id']}/submit/")
    assert response.status_code == 400, response.data
    detail = str(response.data.get("detail") or response.data)
    assert "10,000.00" in detail
    assert "10000.00" not in detail


def test_status_by_entity_links_to_the_current_document(tenant_a, owner_client):
    """Sprint 6.6.6 (§6.3 addition): the per-entity status list used to
    say only approved/not-yet-approved with no way to reach the
    document — now carries its id + real status (draft/pending_
    approval/approved) so the screen can link straight to it."""
    entity = _entity(tenant_a)
    before = owner_client.get("/api/opening-balances/status/")
    row_before = next(r for r in before.data if r["legal_entity"] == str(entity.id))
    assert row_before["current_entry_id"] is None
    assert row_before["current_entry_status"] is None

    created = owner_client.post(
        "/api/opening-balances/",
        {
            "legal_entity": str(entity.id), "kind": "initial",
            "lines": [_line(account=str(_acc(tenant_a, "1900").id), debit_fc="1000", credit_fc="0")],
        },
        format="json",
    )
    assert created.status_code == 201, created.data

    after = owner_client.get("/api/opening-balances/status/")
    row_after = next(r for r in after.data if r["legal_entity"] == str(entity.id))
    assert row_after["current_entry_id"] == created.data["id"]
    assert row_after["current_entry_status"] == "draft"


def test_opening_in_closed_period_blocks_readiness(tenant_a, owner_client):
    from apps.accounting.models import FiscalPeriod

    period = FiscalPeriod.objects.get(fiscal_year__tenant=tenant_a, fiscal_year__name="2026", seq=1)
    close_period(period, list(tenant_a.users.all())[0], acknowledge_warnings=True)

    entity = _entity(tenant_a)
    response = owner_client.post(
        "/api/opening-balances/",
        {
            "legal_entity": str(entity.id), "kind": "initial",
            "lines": [
                _line(account=str(_acc(tenant_a, "1900").id), debit_fc="100"),
                _line(account=str(_acc(tenant_a, "3100").id), credit_fc="100"),
            ],
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    readiness = owner_client.get(f"/api/opening-balances/{response.data['id']}/readiness/")
    codes = [item["code"] for item in readiness.data["items"]]
    assert "period_not_open" in codes


# ---------------------------------------------------------------------
# Two-stage written approval (decision 8)
# ---------------------------------------------------------------------


def _balanced_initial(client, tenant, entity):
    response = client.post(
        "/api/opening-balances/",
        {
            "legal_entity": str(entity.id), "kind": "initial",
            "lines": [
                _line(account=str(_acc(tenant, "1900").id), debit_fc="1000"),
                _line(account=str(_acc(tenant, "3100").id), credit_fc="1000"),
            ],
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    return response.data["id"]


def test_self_approval_rejected_when_not_single_user_tenant(tenant_a, user_a):
    _seed_opening_balance_rule(tenant_a)
    UserFactory(tenant=tenant_a, email="second-owner@ob.test").roles.add(_roles(tenant_a)["Owner"])
    client = _client(user_a)
    entity = _entity(tenant_a)
    entry_id = _balanced_initial(client, tenant_a, entity)
    submitted = client.post(f"/api/opening-balances/{entry_id}/submit/")
    assert submitted.status_code == 200, submitted.data
    response = client.post(
        f"/api/opening-balances/{entry_id}/approve/",
        {"attestation_text": "أقر بصحة هذه الأرصدة الافتتاحية وفق السجلات المتاحة"},
        format="json",
    )
    assert response.status_code == 403, response.data


def test_approve_without_attestation_rejected(tenant_a, owner_client):
    entity = _entity(tenant_a)
    entry_id = _balanced_initial(owner_client, tenant_a, entity)
    owner_client.post(f"/api/opening-balances/{entry_id}/submit/")
    response = owner_client.post(f"/api/opening-balances/{entry_id}/approve/", {}, format="json")
    assert response.status_code == 400, response.data


def test_single_user_tenant_approve_posts_journal_entry_and_stamps_entity(tenant_a, owner_client, user_a):
    entity = _entity(tenant_a)
    entry_id = _balanced_initial(owner_client, tenant_a, entity)
    owner_client.post(f"/api/opening-balances/{entry_id}/submit/")
    attestation = "أقر بصحة هذه الأرصدة الافتتاحية وفق السجلات المتاحة لديّ"
    response = owner_client.post(
        f"/api/opening-balances/{entry_id}/approve/", {"attestation_text": attestation}, format="json"
    )
    assert response.status_code == 200, response.data
    assert response.data["status"] == "approved"
    assert response.data["attestation_text"] == attestation

    entry = OpeningBalanceEntry.objects.get(id=entry_id)
    je = entry.journal_entry
    assert je.status == JournalEntry.Status.POSTED
    assert je.is_opening is True
    assert je.date == entry.opening_date
    debit_total = sum((line.debit for line in je.lines.all()), Decimal("0"))
    credit_total = sum((line.credit for line in je.lines.all()), Decimal("0"))
    assert debit_total == credit_total == Decimal("1000.00")

    entity.refresh_from_db()
    assert entity.opening_approved_at is not None

    log = AuditLog.objects.filter(action="opening_balance.approved", target_id=entry.id).first()
    assert log is not None
    assert log.after["attestation_text"] == attestation


def test_reverse_opening_journal_entry_rejected_409(tenant_a, owner_client, user_a):
    entity = _entity(tenant_a)
    entry_id = _balanced_initial(owner_client, tenant_a, entity)
    owner_client.post(f"/api/opening-balances/{entry_id}/submit/")
    owner_client.post(
        f"/api/opening-balances/{entry_id}/approve/",
        {"attestation_text": "أقر بصحة هذه الأرصدة الافتتاحية وفق السجلات المتاحة لديّ"},
        format="json",
    )
    je_id = OpeningBalanceEntry.objects.get(id=entry_id).journal_entry_id
    response = owner_client.post(
        f"/api/journal-entries/{je_id}/reverse/", {"reason": "محاولة عكس قيد افتتاح"}, format="json"
    )
    assert response.status_code == 409, response.data


def test_editing_lines_after_approval_rejected_409(tenant_a, owner_client, user_a):
    entity = _entity(tenant_a)
    entry_id = _balanced_initial(owner_client, tenant_a, entity)
    owner_client.post(f"/api/opening-balances/{entry_id}/submit/")
    owner_client.post(
        f"/api/opening-balances/{entry_id}/approve/",
        {"attestation_text": "أقر بصحة هذه الأرصدة الافتتاحية وفق السجلات المتاحة لديّ"},
        format="json",
    )
    response = owner_client.patch(
        f"/api/opening-balances/{entry_id}/lines/",
        {"lines": [_line(account=str(_acc(tenant_a, "1900").id), debit_fc="1")]},
        format="json",
    )
    assert response.status_code == 409, response.data


def test_adjustment_balanced_is_approved_and_posted(tenant_a, owner_client, user_a):
    entity = _entity(tenant_a)
    initial_id = _balanced_initial(owner_client, tenant_a, entity)
    owner_client.post(f"/api/opening-balances/{initial_id}/submit/")
    owner_client.post(
        f"/api/opening-balances/{initial_id}/approve/",
        {"attestation_text": "أقر بصحة هذه الأرصدة الافتتاحية وفق السجلات المتاحة لديّ"},
        format="json",
    )

    response = owner_client.post(
        "/api/opening-balances/",
        {
            "legal_entity": str(entity.id), "kind": "adjustment",
            "lines": [
                _line(account=str(_acc(tenant_a, "1900").id), debit_fc="50"),
                _line(account=str(_acc(tenant_a, "3100").id), credit_fc="50"),
            ],
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    adjustment_id = response.data["id"]
    initial = OpeningBalanceEntry.objects.get(id=initial_id)
    adjustment = OpeningBalanceEntry.objects.get(id=adjustment_id)
    assert adjustment.opening_date == initial.opening_date

    owner_client.post(f"/api/opening-balances/{adjustment_id}/submit/")
    response = owner_client.post(
        f"/api/opening-balances/{adjustment_id}/approve/",
        {"attestation_text": "أقر بصحة تعديل الأرصدة الافتتاحية وفق السجلات المتاحة"},
        format="json",
    )
    assert response.status_code == 200, response.data
    adjustment.refresh_from_db()
    assert adjustment.journal_entry.status == JournalEntry.Status.POSTED
    assert adjustment.journal_entry.is_opening is True


def test_tenant_isolation(tenant_a, tenant_b, owner_client, user_b):
    entity = _entity(tenant_a)
    entry_id = _balanced_initial(owner_client, tenant_a, entity)
    _seed_opening_balance_rule(tenant_b)
    other_client = _client(user_b)
    response = other_client.get(f"/api/opening-balances/{entry_id}/")
    assert response.status_code == 404


# ---------------------------------------------------------------------
# Sprint 6.9.1 (item D, decision 6): zero-line INITIAL — an entity that
# started activity inside the system, nothing to open.
# ---------------------------------------------------------------------


def test_empty_initial_is_created_submitted_and_approved_without_a_journal_entry(tenant_a, owner_client, user_a):
    entity = _entity(tenant_a)
    created = owner_client.post(
        "/api/opening-balances/", {"legal_entity": str(entity.id), "kind": "initial", "lines": []}, format="json"
    )
    assert created.status_code == 201, created.data
    entry_id = created.data["id"]

    submitted = owner_client.post(f"/api/opening-balances/{entry_id}/submit/")
    assert submitted.status_code == 200, submitted.data

    response = owner_client.post(
        f"/api/opening-balances/{entry_id}/approve/",
        {"attestation_text": "لا أرصدة افتتاحية — بدأ الكيان نشاطه داخل النظام"},
        format="json",
    )
    assert response.status_code == 200, response.data

    entry = OpeningBalanceEntry.objects.get(id=entry_id)
    assert entry.journal_entry_id is None

    entity.refresh_from_db()
    assert entity.opening_approved_at is not None

    summary = owner_client.get("/api/dashboard/summary/")
    assert summary.status_code == 200, summary.data
    assert entity.name not in summary.data["opening_not_approved"]


# ---------------------------------------------------------------------
# Sprint 6.6.3d (UAT 6 finding A, pulled forward from 6.6.5's unified
# delete rule): an unbalanced draft can be edited back into balance,
# and a draft/rejected entry can be soft-deleted — the exact gap that
# locked a legal entity out permanently on staging (the one-INITIAL-
# per-entity guard never let go of an unbalanced, unfixable draft).
# ---------------------------------------------------------------------


def test_unbalanced_draft_edited_to_balanced_then_submit_succeeds(tenant_a, owner_client):
    entity = _entity(tenant_a)
    created = owner_client.post(
        "/api/opening-balances/",
        {
            "legal_entity": str(entity.id), "kind": "initial",
            "lines": [_line(account=str(_acc(tenant_a, "1900").id), debit_fc="1000")],
        },
        format="json",
    )
    assert created.status_code == 201, created.data
    entry_id = created.data["id"]

    patched = owner_client.patch(
        f"/api/opening-balances/{entry_id}/lines/",
        {
            "lines": [
                _line(account=str(_acc(tenant_a, "1900").id), debit_fc="1000"),
                _line(account=str(_acc(tenant_a, "3100").id), credit_fc="1000"),
            ]
        },
        format="json",
    )
    assert patched.status_code == 200, patched.data
    assert len(patched.data["lines"]) == 2

    submitted = owner_client.post(f"/api/opening-balances/{entry_id}/submit/")
    assert submitted.status_code == 200, submitted.data


def test_delete_draft_then_create_new_initial_for_same_entity_succeeds(tenant_a, owner_client):
    entity = _entity(tenant_a)
    created = owner_client.post(
        "/api/opening-balances/",
        {
            "legal_entity": str(entity.id), "kind": "initial",
            "lines": [_line(account=str(_acc(tenant_a, "1900").id), debit_fc="1000")],
        },
        format="json",
    )
    assert created.status_code == 201, created.data
    entry_id = created.data["id"]

    # Before the fix, this second create would 400 ("يوجد بالفعل مستند
    # افتتاح أولي") with no way out at all — the exact lockout UAT 6
    # found on staging.
    blocked = owner_client.post(
        "/api/opening-balances/",
        {"legal_entity": str(entity.id), "kind": "initial", "lines": []},
        format="json",
    )
    assert blocked.status_code == 400, blocked.data

    deleted = owner_client.delete(f"/api/opening-balances/{entry_id}/")
    assert deleted.status_code == 204, deleted.data

    recreated = owner_client.post(
        "/api/opening-balances/",
        {
            "legal_entity": str(entity.id), "kind": "initial",
            "lines": [
                _line(account=str(_acc(tenant_a, "1900").id), debit_fc="1000"),
                _line(account=str(_acc(tenant_a, "3100").id), credit_fc="1000"),
            ],
        },
        format="json",
    )
    assert recreated.status_code == 201, recreated.data

    # The deleted draft is gone from the UI entirely — list and direct
    # retrieve both treat it as not found.
    assert owner_client.get(f"/api/opening-balances/{entry_id}/").status_code == 404
    list_ids = [row["id"] for row in owner_client.get("/api/opening-balances/").data["results"]]
    assert entry_id not in list_ids


def test_delete_rejected_entry_succeeds(tenant_a, user_a):
    """reject() itself needs no second-user exemption (unlike approve)
    — the same owner who submitted it can reject it."""
    _seed_opening_balance_rule(tenant_a)
    client = _client(user_a)
    entity = _entity(tenant_a)
    entry_id = _balanced_initial(client, tenant_a, entity)
    client.post(f"/api/opening-balances/{entry_id}/submit/")
    rejected = client.post(f"/api/opening-balances/{entry_id}/reject/", {"reason": "بيانات خاطئة"}, format="json")
    assert rejected.status_code == 200, rejected.data

    deleted = client.delete(f"/api/opening-balances/{entry_id}/")
    assert deleted.status_code == 204, deleted.data


def test_delete_approved_entry_rejected_409(tenant_a, owner_client, user_a):
    entity = _entity(tenant_a)
    entry_id = _balanced_initial(owner_client, tenant_a, entity)
    owner_client.post(f"/api/opening-balances/{entry_id}/submit/")
    owner_client.post(
        f"/api/opening-balances/{entry_id}/approve/",
        {"attestation_text": "أقر بصحة هذه الأرصدة الافتتاحية وفق السجلات المتاحة لديّ"},
        format="json",
    )
    response = owner_client.delete(f"/api/opening-balances/{entry_id}/")
    assert response.status_code == 409, response.data
    assert OpeningBalanceEntry.objects.get(id=entry_id).deleted_at is None


def test_delete_pending_approval_entry_rejected_409(tenant_a, owner_client):
    entity = _entity(tenant_a)
    entry_id = _balanced_initial(owner_client, tenant_a, entity)
    owner_client.post(f"/api/opening-balances/{entry_id}/submit/")
    response = owner_client.delete(f"/api/opening-balances/{entry_id}/")
    assert response.status_code == 409, response.data


def test_delete_logs_audit_entry(tenant_a, owner_client, user_a):
    entity = _entity(tenant_a)
    created = owner_client.post(
        "/api/opening-balances/",
        {"legal_entity": str(entity.id), "kind": "initial", "lines": []},
        format="json",
    )
    entry_id = created.data["id"]
    owner_client.delete(f"/api/opening-balances/{entry_id}/")

    assert AuditLog.objects.filter(
        tenant_id=tenant_a.id, action="opening_balance.deleted", target_id=entry_id,
    ).exists()
