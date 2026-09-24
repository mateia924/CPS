"""Sprint 6.4 (docs/SYSTEM_ANALYSIS.md 3.15.4, sprint-6.md decisions
9-10): recurring entries (prepaid expenses / deferred revenue /
accruals) — installment split, Celery-beat + on-demand generation,
skip-on-closed-period + regenerate, auto-created next fiscal year,
segregation of duties, cancel, tenant isolation. Real HTTP API + real
Postgres throughout (docs/SYSTEM_ANALYSIS.md §11: manual testing never
writes to a live tenant — pytest against the isolated test database is
the only sanctioned write path here)."""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.access.models import Role
from apps.access.services import seed_default_roles
from apps.accounting.models import (
    Account,
    FiscalPeriod,
    FiscalYear,
    JournalEntry,
    RecurringEntry,
    RecurringInstallment,
)
from apps.accounting.periods import close_period
from apps.accounting.recurring import generate_due_installments
from apps.approvals.models import ApprovalRule

from .factories import LegalEntityFactory, UserFactory


def _roles(tenant):
    existing = {r.name: r for r in Role.objects.filter(tenant=tenant, is_system=True)}
    return existing or seed_default_roles(tenant)


def _seed_recurring_rule(tenant):
    owner_role = _roles(tenant)["Owner"]
    return ApprovalRule.objects.get_or_create(
        tenant=tenant, doc_type=ApprovalRule.DocType.RECURRING_ENTRY, min_amount=0,
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


def _period(tenant, seq, year="2026"):
    return FiscalPeriod.objects.get(fiscal_year__tenant=tenant, fiscal_year__name=year, seq=seq)


@pytest.fixture
def owner_client(tenant_a, user_a):
    _seed_recurring_rule(tenant_a)
    return _client(user_a)


def _create(client, tenant, entity, total, count, first_period_seq=1, kind="prepaid_expense"):
    response = client.post(
        "/api/recurring-entries/",
        {
            "legal_entity": str(entity.id), "kind": kind, "description": "إيجار مقدم",
            "from_account": str(_acc(tenant, "1900").id), "to_account": str(_acc(tenant, "5100").id),
            "total_amount_base": str(total), "installments_count": count,
            "first_period": str(_period(tenant, first_period_seq).id),
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    return response.data["id"]


def _submit_and_approve(client, entry_id):
    submitted = client.post(f"/api/recurring-entries/{entry_id}/submit/")
    assert submitted.status_code == 200, submitted.data
    approved = client.post(f"/api/recurring-entries/{entry_id}/approve/")
    assert approved.status_code == 200, approved.data
    return approved.data


def test_equal_split_twelve_installments(tenant_a, owner_client):
    entity = _entity(tenant_a)
    entry_id = _create(owner_client, tenant_a, entity, "12000", 12)
    data = _submit_and_approve(owner_client, entry_id)
    installments = data["installments"]
    assert len(installments) == 12
    assert all(Decimal(i["amount_base"]) == Decimal("1000.00") for i in installments)
    assert [i["due_date"] for i in installments] == [
        _period(tenant_a, seq).end_date.isoformat() for seq in range(1, 13)
    ]


def test_remainder_on_last_installment(tenant_a, owner_client):
    entity = _entity(tenant_a)
    entry_id = _create(owner_client, tenant_a, entity, "10000", 3)
    data = _submit_and_approve(owner_client, entry_id)
    amounts = [Decimal(i["amount_base"]) for i in data["installments"]]
    assert amounts == [Decimal("3333.33"), Decimal("3333.33"), Decimal("3333.34")]
    assert sum(amounts, Decimal("0")) == Decimal("10000.00")


def test_generate_due_posts_single_entry_with_correct_lines(tenant_a, owner_client):
    entity = _entity(tenant_a)
    entry_id = _create(owner_client, tenant_a, entity, "3000", 3)
    _submit_and_approve(owner_client, entry_id)

    period1_end = _period(tenant_a, 1).end_date
    result = generate_due_installments(tenant=tenant_a, as_of=period1_end)
    assert result["generated"] == 1

    entry = RecurringEntry.objects.get(id=entry_id)
    installment = entry.installments.get(seq=1)
    assert installment.status == RecurringInstallment.Status.GENERATED
    je = installment.journal_entry
    assert je.status == JournalEntry.Status.POSTED
    assert je.date == period1_end
    assert je.source_type == "recurring"
    lines = {line.account.code: line for line in je.lines.all()}
    assert lines["5100"].debit == Decimal("1000.00")
    assert lines["1900"].credit == Decimal("1000.00")


def test_generate_due_twice_does_not_duplicate(tenant_a, owner_client):
    entity = _entity(tenant_a)
    entry_id = _create(owner_client, tenant_a, entity, "3000", 3)
    _submit_and_approve(owner_client, entry_id)

    period1_end = _period(tenant_a, 1).end_date
    first = generate_due_installments(tenant=tenant_a, as_of=period1_end)
    second = generate_due_installments(tenant=tenant_a, as_of=period1_end)
    assert first["generated"] == 1
    assert second["generated"] == 0

    entry = RecurringEntry.objects.get(id=entry_id)
    assert JournalEntry.objects.filter(tenant=tenant_a, source_type="recurring", source_id=entry.id).count() == 1


def test_closed_period_skips_then_regenerate_after_reopen(tenant_a, owner_client, user_a):
    entity = _entity(tenant_a)
    entry_id = _create(owner_client, tenant_a, entity, "3000", 3)
    _submit_and_approve(owner_client, entry_id)

    period1 = _period(tenant_a, 1)
    close_period(period1, user_a)

    result = generate_due_installments(tenant=tenant_a, as_of=period1.end_date)
    assert result["skipped"] == 1
    installment = RecurringInstallment.objects.get(entry_id=entry_id, seq=1)
    assert installment.status == RecurringInstallment.Status.SKIPPED
    assert installment.skip_reason

    reopened = owner_client.post(f"/api/fiscal-periods/{period1.id}/reopen/", {"reason": "تصحيح"}, format="json")
    assert reopened.status_code == 200, reopened.data

    response = owner_client.post(f"/api/recurring-installments/{installment.id}/regenerate/")
    assert response.status_code == 200, response.data
    installment.refresh_from_db()
    assert installment.status == RecurringInstallment.Status.GENERATED
    assert installment.journal_entry is not None


def test_last_installment_completes_entry(tenant_a, owner_client):
    entity = _entity(tenant_a)
    entry_id = _create(owner_client, tenant_a, entity, "2000", 2)
    _submit_and_approve(owner_client, entry_id)

    generate_due_installments(tenant=tenant_a, as_of=_period(tenant_a, 2).end_date)
    entry = RecurringEntry.objects.get(id=entry_id)
    assert entry.status == RecurringEntry.Status.COMPLETED
    assert entry.installments.filter(status=RecurringInstallment.Status.GENERATED).count() == 2


def test_cancel_only_cancels_due_installments(tenant_a, owner_client):
    entity = _entity(tenant_a)
    entry_id = _create(owner_client, tenant_a, entity, "3000", 3)
    _submit_and_approve(owner_client, entry_id)
    generate_due_installments(tenant=tenant_a, as_of=_period(tenant_a, 1).end_date)

    response = owner_client.post(f"/api/recurring-entries/{entry_id}/cancel/")
    assert response.status_code == 200, response.data
    entry = RecurringEntry.objects.get(id=entry_id)
    assert entry.status == RecurringEntry.Status.CANCELLED
    statuses = {i.seq: i.status for i in entry.installments.all()}
    assert statuses[1] == RecurringInstallment.Status.GENERATED
    assert statuses[2] == RecurringInstallment.Status.CANCELLED
    assert statuses[3] == RecurringInstallment.Status.CANCELLED


def test_schedule_needing_next_year_creates_it_automatically(tenant_a, owner_client):
    entity = _entity(tenant_a)
    # first_period = December 2026 (seq 12); 3 installments run into
    # Jan/Feb 2027, which don't exist yet on tenant_a's calendar-year-
    # 2026-only setup (conftest.py's seed_fiscal_year_for_tenant).
    entry_id = _create(owner_client, tenant_a, entity, "300", 3, first_period_seq=12)
    assert not FiscalYear.objects.filter(tenant=tenant_a, name="2027").exists()
    data = _submit_and_approve(owner_client, entry_id)
    assert len(data["installments"]) == 3
    assert FiscalYear.objects.filter(tenant=tenant_a, name="2027").exists()


def test_creator_cannot_approve_own_schedule(tenant_a, user_a):
    _seed_recurring_rule(tenant_a)
    UserFactory(tenant=tenant_a, email="second-owner@recurring.test").roles.add(_roles(tenant_a)["Owner"])
    client = _client(user_a)
    entity = _entity(tenant_a)
    entry_id = _create(client, tenant_a, entity, "1200", 12)
    submitted = client.post(f"/api/recurring-entries/{entry_id}/submit/")
    assert submitted.status_code == 200, submitted.data
    response = client.post(f"/api/recurring-entries/{entry_id}/approve/")
    assert response.status_code == 403, response.data


def test_tenant_isolation(tenant_a, tenant_b, owner_client, user_b):
    entity = _entity(tenant_a)
    entry_id = _create(owner_client, tenant_a, entity, "1200", 12)
    _seed_recurring_rule(tenant_b)
    other_client = _client(user_b)
    response = other_client.get(f"/api/recurring-entries/{entry_id}/")
    assert response.status_code == 404
