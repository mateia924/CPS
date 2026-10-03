"""Sprint 6.1 (docs/SYSTEM_ANALYSIS.md 3.9, sprint-6.md decisions 1-4):
fiscal years and periods, the posting-date gate, and the period
lifecycle (close/reopen/lock). tenant_a/tenant_b (conftest.py) already
seed a 2026 calendar year (12 open monthly periods) — every date this
file uses is somewhere inside it unless the test is explicitly about a
date that isn't.
"""

import unittest.mock
from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.access.models import Role
from apps.access.services import seed_default_roles
from apps.accounting.models import Account, FiscalPeriod, FiscalYear, JournalEntry, TaxCode
from apps.accounting.periods import create_next_fiscal_year_if_due, seed_fiscal_year_for_tenant
from apps.accounting.services import (
    create_manual_journal_entry,
    post_journal_entry,
    reverse_journal_entry,
    submit_journal_entry_for_approval,
)
from apps.platform.models import AuditLog

from .factories import LegalEntityFactory, PartyFactory, ProductFactory, TenantFactory, UserFactory


def _roles(tenant):
    """Returns this tenant's system roles, seeding them only if they
    don't already exist — client_a's own user_a fixture already seeds
    them for tenant_a; seed_default_roles is not idempotent (unique
    constraint on tenant+name), so a second call would crash."""
    existing = {r.name: r for r in Role.objects.filter(tenant=tenant, is_system=True)}
    return existing or seed_default_roles(tenant)


def _period(tenant, month):
    return FiscalPeriod.objects.get(fiscal_year__tenant=tenant, seq=month, fiscal_year__name="2026")


def _post_manual_entry(tenant, on_date):
    cash = Account.objects.get(tenant=tenant, system_key="CASH")
    sales = Account.objects.get(tenant=tenant, system_key="SALES")
    roles = _roles(tenant)
    user = UserFactory(tenant=tenant, email=f"poster-{on_date}@fiscal-periods.test")
    user.roles.add(roles["Owner"])
    entity = LegalEntityFactory(tenant=tenant)
    entry = create_manual_journal_entry(
        tenant=tenant, user=user, legal_entity=entity, date=on_date,
        line_specs=[
            {"account": cash, "debit_fc": Decimal("10.00"), "credit_fc": Decimal("0")},
            {"account": sales, "debit_fc": Decimal("0"), "credit_fc": Decimal("10.00")},
        ],
        currency="SAR", exchange_rate=Decimal("1"),
    )
    submit_journal_entry_for_approval(entry, user)
    post_journal_entry(entry, user)
    return entry


def _close_period_directly(tenant, seq):
    """Closes months 1..seq in order (sequential-closing rule) via the
    real API, using a fresh Owner — used as setup for tests that need a
    closed period without re-testing the close flow itself each time."""
    roles = _roles(tenant)
    user = UserFactory(tenant=tenant, email=f"closer-seq{seq}-{tenant.id}@fiscal-periods.test")
    user.roles.add(roles["Owner"])
    client = APIClient()
    client.force_authenticate(user=user)
    for month in range(1, seq + 1):
        period = _period(tenant, month)
        if period.status == FiscalPeriod.Status.OPEN:
            response = client.post(
                f"/api/fiscal-periods/{period.id}/close/",
                {"note": "test", "acknowledge_warnings": True}, format="json",
            )
            assert response.status_code == 200, response.data


# ---------------------------------------------------------------------
# Year/period creation
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_registration_creates_a_fiscal_year_with_12_periods(client):
    response = client.post(
        "/api/auth/register/",
        {
            "company_name": "Fiscal Test Co", "subdomain": "fiscal-reg-test",
            "email": "owner@fiscal-reg-test.test", "password": "TestPass!2026",
        },
        content_type="application/json",
    )
    assert response.status_code == 201, response.data
    from apps.tenants.models import Tenant

    tenant = Tenant.objects.get(subdomain="fiscal-reg-test")
    year = FiscalYear.objects.get(tenant=tenant)
    assert year.periods.count() == 12
    assert all(p.status == FiscalPeriod.Status.OPEN for p in year.periods.all())


@pytest.mark.django_db
def test_consecutive_periods_accepted(tenant_a, client_a):
    response = client_a.post(
        "/api/fiscal-years/",
        {"name": "2027", "start_date": "2027-01-01", "end_date": "2027-12-31", "period_length": "monthly"},
        format="json",
    )
    assert response.status_code == 201, response.data
    periods = response.data["periods"]
    assert len(periods) == 12
    for previous, current in zip(periods, periods[1:]):
        assert current["start_date"] > previous["end_date"]


@pytest.mark.django_db
def test_custom_periods_not_covering_the_full_year_rejected(tenant_a, client_a):
    # The declared end dates stop short of the fiscal year's own end
    # date (2028-02-28, not 2028-03-31) — the year's last stretch is
    # left uncovered by any period.
    response = client_a.post(
        "/api/fiscal-years/",
        {
            "name": "2028", "start_date": "2028-01-01", "end_date": "2028-03-31",
            "period_length": "custom",
            "custom_period_end_dates": ["2028-01-31", "2028-02-28"],
        },
        format="json",
    )
    assert response.status_code == 400, response.data


@pytest.mark.django_db
def test_custom_periods_with_a_duplicate_end_date_rejected(tenant_a, client_a):
    # A repeated end date collapses a period to zero/negative length —
    # rejected as "not strictly increasing" rather than silently
    # producing an empty period.
    response = client_a.post(
        "/api/fiscal-years/",
        {
            "name": "2028", "start_date": "2028-01-01", "end_date": "2028-03-31",
            "period_length": "custom",
            "custom_period_end_dates": ["2028-01-31", "2028-01-31", "2028-03-31"],
        },
        format="json",
    )
    assert response.status_code == 400, response.data


@pytest.mark.django_db
def test_year_overlapping_existing_year_rejected(tenant_a, client_a):
    response = client_a.post(
        "/api/fiscal-years/",
        {"name": "overlap", "start_date": "2026-06-01", "end_date": "2027-06-01", "period_length": "monthly"},
        format="json",
    )
    assert response.status_code == 400, response.data


@pytest.mark.django_db
def test_editing_year_boundaries_with_posted_entry_is_409(tenant_a, client_a):
    _post_manual_entry(tenant_a, date(2026, 1, 15))
    year_id = FiscalYear.objects.get(tenant=tenant_a, name="2026").id
    response = client_a.patch(
        f"/api/fiscal-years/{year_id}/",
        {"name": "2026", "start_date": "2026-01-01", "end_date": "2026-12-30", "period_length": "monthly"},
        format="json",
    )
    assert response.status_code == 409, response.data


@pytest.mark.django_db
def test_editing_year_boundaries_without_posted_entries_succeeds(tenant_a, client_a):
    year_id = FiscalYear.objects.get(tenant=tenant_a, name="2026").id
    response = client_a.patch(
        f"/api/fiscal-years/{year_id}/",
        {"name": "2026", "start_date": "2026-01-01", "end_date": "2026-12-31", "period_length": "quarterly"},
        format="json",
    )
    assert response.status_code == 200, response.data
    assert len(response.data["periods"]) == 4


@pytest.mark.django_db
def test_renaming_a_year_with_posted_entries_still_succeeds(tenant_a, client_a):
    """Sprint 6.6.5 (§6.2 addition): a pure rename (identical resulting
    period ranges) never touches a single FiscalPeriod row, so it's
    never blocked by the strict "completely empty" bar that real
    boundary moves require — the year's NAME is always editable."""
    _post_manual_entry(tenant_a, date(2026, 1, 15))
    year_id = FiscalYear.objects.get(tenant=tenant_a, name="2026").id
    response = client_a.patch(
        f"/api/fiscal-years/{year_id}/",
        {"name": "السنة 2026", "start_date": "2026-01-01", "end_date": "2026-12-31", "period_length": "monthly"},
        format="json",
    )
    assert response.status_code == 200, response.data
    assert response.data["name"] == "السنة 2026"


# ---------------------------------------------------------------------
# Sprint 6.6.5 (§6.2 addition): fiscal years enter the unified delete
# rule — soft delete only when completely empty (no document of any
# status, no scheduled installment, no closed/locked period).
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_delete_empty_year_soft_deletes(tenant_a, client_a):
    created = client_a.post(
        "/api/fiscal-years/",
        {"name": "2030", "start_date": "2030-01-01", "end_date": "2030-12-31", "period_length": "monthly"},
        format="json",
    )
    year_id = created.data["id"]

    deleted = client_a.delete(f"/api/fiscal-years/{year_id}/")
    assert deleted.status_code == 204, deleted.data

    year = FiscalYear.objects.get(id=year_id)
    assert year.deleted_at is not None
    assert client_a.get(f"/api/fiscal-years/{year_id}/").status_code == 404


@pytest.mark.django_db
def test_delete_year_with_a_draft_document_is_rejected(tenant_a, client_a):
    """Stricter than the document-level delete rule on purpose — a
    DRAFT journal entry is itself freely deletable, but the YEAR it's
    dated in is not, since deleting the year would otherwise orphan
    it (sprint 6.6.5 §6.2: "ولا حتى مسودة")."""
    create_manual_journal_entry(
        tenant=tenant_a, user=UserFactory(tenant=tenant_a), legal_entity=LegalEntityFactory(tenant=tenant_a),
        date=date(2026, 3, 1),
        line_specs=[
            {"account": Account.objects.get(tenant=tenant_a, system_key="CASH"), "debit_fc": Decimal("5"), "credit_fc": Decimal("0")},
            {"account": Account.objects.get(tenant=tenant_a, system_key="SALES"), "debit_fc": Decimal("0"), "credit_fc": Decimal("5")},
        ],
        currency="SAR", exchange_rate=Decimal("1"),
    )
    year_id = FiscalYear.objects.get(tenant=tenant_a, name="2026").id

    response = client_a.delete(f"/api/fiscal-years/{year_id}/")
    assert response.status_code == 409, response.data
    assert "journal entry" in response.data["detail"]


@pytest.mark.django_db
def test_delete_year_with_a_closed_period_is_rejected(tenant_a, client_a):
    period = _period(tenant_a, 1)
    period.status = FiscalPeriod.Status.CLOSED
    period.save(update_fields=["status"])
    year_id = FiscalYear.objects.get(tenant=tenant_a, name="2026").id

    response = client_a.delete(f"/api/fiscal-years/{year_id}/")
    assert response.status_code == 409, response.data
    assert "closed" in response.data["detail"].lower() or "locked" in response.data["detail"].lower()


# ---------------------------------------------------------------------
# The posting-date gate
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_document_dated_in_a_closed_period_rejected_on_save(tenant_a, client_a):
    _close_period_directly(tenant_a, 1)  # January
    customer = PartyFactory(tenant=tenant_a)
    product = ProductFactory(tenant=tenant_a)
    tax_code = TaxCode.objects.get(tenant=tenant_a, code="Z")

    response = client_a.post(
        "/api/invoices/",
        {
            "customer": str(customer.id), "issue_date": "2026-01-15",
            "lines": [{"product": str(product.id), "quantity": "1", "tax_code": str(tax_code.id)}],
        },
        format="json",
    )
    assert response.status_code == 400, response.data


@pytest.mark.django_db
def test_post_journal_entry_rejects_a_closed_period_called_directly(tenant_a):
    """Sprint 7.0 (6.6.10 item 0-bis): calls `post_journal_entry` itself
    directly — not through the API — so this keeps working regardless
    of which future caller (sprint 7's own new posting paths included)
    reaches it. `post_journal_entry` already calls `assert_open_period`
    internally (apps/accounting/services.py); no code change needed —
    this only proves it. The approved-but-unposted state constructed
    here (period closed out from under an already-approved entry) is
    not reachable through the real close-period flow (its own BLOCK
    check refuses to close over an approved-but-unposted document) —
    manipulated directly here specifically to exercise the function's
    own defense, independent of whether that flow stays airtight."""
    from django.core.exceptions import ValidationError

    cash = Account.objects.get(tenant=tenant_a, system_key="CASH")
    sales = Account.objects.get(tenant=tenant_a, system_key="SALES")
    roles = _roles(tenant_a)
    user = UserFactory(tenant=tenant_a, email="direct-post-closed@fiscal-periods.test")
    user.roles.add(roles["Owner"])
    entity = LegalEntityFactory(tenant=tenant_a)
    entry = create_manual_journal_entry(
        tenant=tenant_a, user=user, legal_entity=entity, date=date(2026, 1, 15),
        line_specs=[
            {"account": cash, "debit_fc": Decimal("10.00"), "credit_fc": Decimal("0")},
            {"account": sales, "debit_fc": Decimal("0"), "credit_fc": Decimal("10.00")},
        ],
        currency="SAR", exchange_rate=Decimal("1"),
    )
    submit_journal_entry_for_approval(entry, user)
    entry.refresh_from_db()
    assert entry.status == JournalEntry.Status.APPROVED

    january = _period(tenant_a, 1)
    january.status = FiscalPeriod.Status.CLOSED
    january.save(update_fields=["status"])

    with pytest.raises(ValidationError):
        post_journal_entry(entry, user)

    entry.refresh_from_db()
    assert entry.status == JournalEntry.Status.APPROVED  # unchanged — the write never happened


@pytest.mark.django_db
def test_date_with_no_covering_period_rejected(tenant_a, client_a):
    customer = PartyFactory(tenant=tenant_a)
    product = ProductFactory(tenant=tenant_a)
    tax_code = TaxCode.objects.get(tenant=tenant_a, code="Z")

    response = client_a.post(
        "/api/invoices/",
        {
            "customer": str(customer.id), "issue_date": "2025-01-01",
            "lines": [{"product": str(product.id), "quantity": "1", "tax_code": str(tax_code.id)}],
        },
        format="json",
    )
    assert response.status_code == 400, response.data


@pytest.mark.django_db
def test_reversal_dated_today_accepted_despite_original_periods_closure(tenant_a):
    entry = _post_manual_entry(tenant_a, date(2026, 1, 15))
    _close_period_directly(tenant_a, 1)

    roles = _roles(tenant_a)
    approver = UserFactory(tenant=tenant_a, email="reverser@fiscal-periods.test")
    approver.roles.add(roles["Owner"])
    # today() in this environment is 2026-09-24 — inside the still-open
    # September period regardless of January's closure.
    reversal = reverse_journal_entry(entry, approver, "test reversal")
    assert reversal.status == JournalEntry.Status.POSTED


@pytest.mark.django_db
def test_reversal_dated_into_a_closed_period_rejected(tenant_a):
    from django.core.exceptions import ValidationError

    entry = _post_manual_entry(tenant_a, date(2026, 2, 15))
    _close_period_directly(tenant_a, 2)

    roles = _roles(tenant_a)
    approver = UserFactory(tenant=tenant_a, email="reverser2@fiscal-periods.test")
    approver.roles.add(roles["Owner"])
    with pytest.raises(ValidationError):
        reverse_journal_entry(entry, approver, "test reversal", date=date(2026, 2, 20))


@pytest.mark.django_db
def test_tenant_isolation_on_fiscal_years_and_periods(tenant_a, tenant_b, client_a):
    year_b = FiscalYear.objects.get(tenant=tenant_b, name="2026")
    response = client_a.get(f"/api/fiscal-years/{year_b.id}/")
    assert response.status_code == 404

    period_b = FiscalPeriod.objects.filter(fiscal_year=year_b).first()
    response = client_a.get(f"/api/fiscal-periods/{period_b.id}/")
    assert response.status_code == 404


# ---------------------------------------------------------------------
# Close / reopen / lock lifecycle
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_closing_before_previous_period_rejected(tenant_a, client_a):
    february = _period(tenant_a, 2)
    response = client_a.post(f"/api/fiscal-periods/{february.id}/close/", {}, format="json")
    assert response.status_code == 400, response.data


@pytest.mark.django_db
def test_reopen_requires_a_reason_then_logs_audit(tenant_a, client_a):
    _close_period_directly(tenant_a, 1)
    january = _period(tenant_a, 1)

    response = client_a.post(f"/api/fiscal-periods/{january.id}/reopen/", {}, format="json")
    assert response.status_code == 400, response.data

    response = client_a.post(f"/api/fiscal-periods/{january.id}/reopen/", {"reason": "correction needed"}, format="json")
    assert response.status_code == 200, response.data
    january.refresh_from_db()
    assert january.status == FiscalPeriod.Status.OPEN
    assert AuditLog.objects.filter(action="fiscal_period.reopened", target_id=january.id).exists()


@pytest.mark.django_db
def test_lock_requires_attestation_then_is_never_reopenable(tenant_a, client_a):
    _close_period_directly(tenant_a, 1)
    january = _period(tenant_a, 1)

    response = client_a.post(f"/api/fiscal-periods/{january.id}/lock/", {"lock_attestation": "too short"}, format="json")
    assert response.status_code == 400, response.data

    response = client_a.post(
        f"/api/fiscal-periods/{january.id}/lock/",
        {"lock_attestation": "أُقفلت هذه الفترة نهائيًا بعد التحقق الكامل من كل أرصدتها."},
        format="json",
    )
    assert response.status_code == 200, response.data
    january.refresh_from_db()
    assert january.status == FiscalPeriod.Status.LOCKED

    response = client_a.post(f"/api/fiscal-periods/{january.id}/reopen/", {"reason": "x"}, format="json")
    assert response.status_code == 409, response.data


@pytest.mark.django_db
def test_year_locks_once_every_period_is_locked(tenant_a, client_a):
    year_id = FiscalYear.objects.get(tenant=tenant_a, name="2026").id
    response = client_a.patch(
        f"/api/fiscal-years/{year_id}/",
        {"name": "2026", "start_date": "2026-01-01", "end_date": "2026-12-31", "period_length": "quarterly"},
        format="json",
    )
    assert response.status_code == 200, response.data

    year = FiscalYear.objects.get(pk=year_id)
    for period in year.periods.order_by("seq"):
        close_response = client_a.post(
            f"/api/fiscal-periods/{period.id}/close/", {"acknowledge_warnings": True}, format="json"
        )
        assert close_response.status_code == 200, close_response.data
        lock_response = client_a.post(
            f"/api/fiscal-periods/{period.id}/lock/",
            {"lock_attestation": "إقرار نهائي بإقفال هذه الفترة بعد المراجعة الكاملة."},
            format="json",
        )
        assert lock_response.status_code == 200, lock_response.data

    year.refresh_from_db()
    assert year.status == FiscalYear.Status.LOCKED


# ---------------------------------------------------------------------
# The daily beat
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_beat_creates_next_year_once_within_30_day_horizon(db):
    from apps.accounting.services import seed_chart_of_accounts

    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    seed_fiscal_year_for_tenant(tenant, start_date=date(2025, 10, 10))  # ends 2026-10-09

    with unittest.mock.patch("django.utils.timezone.localdate", return_value=date(2026, 9, 20)):
        created = create_next_fiscal_year_if_due()
    assert any(y.tenant_id == tenant.id for y in created)
    assert FiscalYear.objects.filter(tenant=tenant).count() == 2

    with unittest.mock.patch("django.utils.timezone.localdate", return_value=date(2026, 9, 20)):
        created_again = create_next_fiscal_year_if_due()
    assert not any(y.tenant_id == tenant.id for y in created_again)
    assert FiscalYear.objects.filter(tenant=tenant).count() == 2
