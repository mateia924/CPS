"""Sprint 5.7 (docs/CFO_REVIEW_1.md §3): financial controls #1 —
control accounts (C2), the deactivated-account posting guard (C13),
and the get_rate improvements (C14). C1 (the Postgres trigger) and C4
(row locking) each have their own dedicated test coverage — C1 in
test_db_triggers.py, C4 in test_journal_engine.py.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.accounting.models import Account, JournalEntry, TaxCode
from apps.treasury.models import ExchangeRate
from apps.treasury.services import get_rate

from .factories import PartyFactory, ProductFactory, UserFactory


def _leaf_pair(tenant):
    cash = Account.objects.get(tenant=tenant, system_key="CASH")
    sales = Account.objects.get(tenant=tenant, system_key="SALES")
    return cash, sales


@pytest.mark.django_db
def test_manual_jv_on_customer_control_account_rejected_without_override(tenant_a, client_a):
    from apps.organization.models import LegalEntity
    from apps.sales.services import create_invoice, issue_invoice

    branch = LegalEntity.objects.get(tenant=tenant_a, entity_type=LegalEntity.Type.BRANCH)
    party = PartyFactory(tenant=tenant_a)
    product = ProductFactory(tenant=tenant_a, unit_price="100.00", tax_rate="0")
    tax_code_z = TaxCode.objects.get(tenant=tenant_a, code="Z")
    from apps.accounts.models import User

    owner = User.objects.get(tenant=tenant_a, email="owner@tenant-a.test")
    invoice = create_invoice(
        tenant=tenant_a, party=party, legal_entity=branch, issue_date=date(2026, 1, 1),
        line_inputs=[{"product": product, "quantity": Decimal("1"), "cost_center": None, "tax_code": tax_code_z}],
        currency="SAR", exchange_rate=Decimal("1"), created_by=owner,
    )
    issue_invoice(invoice, owner)

    customer_account = Account.objects.get(tenant=tenant_a, party=party, parent__system_key="CUSTOMERS")
    assert customer_account.allow_manual_posting is False
    cash = Account.objects.get(tenant=tenant_a, system_key="CASH")

    response = client_a.post(
        "/api/journal-entries/",
        {
            "legal_entity": str(branch.id), "date": "2026-01-02",
            "lines": [
                {"account": str(cash.id), "debit_fc": "50.00", "credit_fc": "0"},
                {"account": str(customer_account.id), "debit_fc": "0", "credit_fc": "50.00"},
            ],
        },
        format="json",
    )
    assert response.status_code == 400, response.data
    assert "رقابة" in response.data["detail"] or "control" in response.data["detail"].lower()


@pytest.mark.django_db
def test_manual_jv_on_control_account_with_override_and_permission_succeeds(tenant_a, client_a):
    from apps.organization.models import LegalEntity

    branch = LegalEntity.objects.get(tenant=tenant_a, entity_type=LegalEntity.Type.BRANCH)
    cash = Account.objects.get(tenant=tenant_a, system_key="CASH")
    vat_output = Account.objects.get(tenant=tenant_a, system_key="VAT_OUTPUT")
    # client_a authenticates as the tenant's Owner (seeded with every
    # permission, including accounting.post_control_accounts).
    response = client_a.post(
        "/api/journal-entries/",
        {
            "legal_entity": str(branch.id), "date": "2026-01-02",
            "override_reason": "تصحيح خطأ ترحيل يدوي بموافقة المالك",
            "lines": [
                {"account": str(cash.id), "debit_fc": "0", "credit_fc": "10.00"},
                {"account": str(vat_output.id), "debit_fc": "10.00", "credit_fc": "0"},
            ],
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    entry = JournalEntry.objects.get(id=response.data["id"])
    assert entry.is_control_override is True


@pytest.mark.django_db
def test_manual_jv_on_control_account_without_permission_forbidden(tenant_a, client_a):
    """An Accountant (no accounting.post_control_accounts) supplying an
    override_reason still gets 403 — the reason alone isn't enough."""
    from rest_framework.test import APIClient

    from apps.access.models import UserEntityAccess
    from apps.organization.models import LegalEntity

    branch = LegalEntity.objects.get(tenant=tenant_a, entity_type=LegalEntity.Type.BRANCH)
    from apps.access.models import Role

    accountant_role = Role.objects.get(tenant=tenant_a, name="Accountant", is_system=True)
    accountant = UserFactory(tenant=tenant_a, email="accountant@control-override.test")
    accountant.roles.add(accountant_role)
    UserEntityAccess.objects.create(user=accountant, legal_entity=branch)
    client = APIClient()
    client.force_authenticate(user=accountant)

    cash = Account.objects.get(tenant=tenant_a, system_key="CASH")
    vat_output = Account.objects.get(tenant=tenant_a, system_key="VAT_OUTPUT")
    response = client.post(
        "/api/journal-entries/",
        {
            "legal_entity": str(branch.id), "date": "2026-01-02",
            "override_reason": "محاولة محاسب",
            "lines": [
                {"account": str(cash.id), "debit_fc": "0", "credit_fc": "10.00"},
                {"account": str(vat_output.id), "debit_fc": "10.00", "credit_fc": "0"},
            ],
        },
        format="json",
    )
    assert response.status_code == 403, response.data


@pytest.mark.django_db
def test_posting_to_deactivated_account_rejected(tenant_a, client_a):
    from apps.organization.models import LegalEntity

    branch = LegalEntity.objects.get(tenant=tenant_a, entity_type=LegalEntity.Type.BRANCH)
    cash = Account.objects.get(tenant=tenant_a, system_key="CASH")
    expense = Account.objects.filter(tenant=tenant_a, code="5100").first()
    expense.is_active = False
    expense.save(update_fields=["is_active"])

    response = client_a.post(
        "/api/journal-entries/",
        {
            "legal_entity": str(branch.id), "date": "2026-01-02",
            "lines": [
                {"account": str(cash.id), "debit_fc": "0", "credit_fc": "10.00"},
                {"account": str(expense.id), "debit_fc": "10.00", "credit_fc": "0"},
            ],
        },
        format="json",
    )
    assert response.status_code == 400, response.data


@pytest.mark.django_db
def test_deactivating_account_with_nonzero_balance_rejected(tenant_a, client_a):
    from apps.organization.models import LegalEntity

    branch = LegalEntity.objects.get(tenant=tenant_a, entity_type=LegalEntity.Type.BRANCH)
    cash, sales = _leaf_pair(tenant_a)
    response = client_a.post(
        "/api/journal-entries/",
        {
            "legal_entity": str(branch.id), "date": "2026-01-02",
            "lines": [
                {"account": str(cash.id), "debit_fc": "10.00", "credit_fc": "0"},
                {"account": str(sales.id), "debit_fc": "0", "credit_fc": "10.00"},
            ],
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    entry_id = response.data["id"]
    submit = client_a.post(f"/api/journal-entries/{entry_id}/submit/")
    assert submit.data["status"] in ("approved", "pending_approval")
    if submit.data["status"] == "approved":
        client_a.post(f"/api/journal-entries/{entry_id}/post/")

    deactivate = client_a.post(f"/api/accounts/{cash.id}/deactivate/")
    assert deactivate.status_code == 409, deactivate.data


@pytest.mark.django_db
def test_deactivating_account_with_active_children_rejected(tenant_a, client_a):
    parent = Account.objects.filter(tenant=tenant_a, code="1000").first() or Account.objects.get(
        tenant=tenant_a, system_key="CASH"
    ).parent
    if parent is None or not parent.children.filter(is_active=True).exists():
        pytest.skip("chart template has no active-parent/child pair to exercise")
    response = client_a.post(f"/api/accounts/{parent.id}/deactivate/")
    assert response.status_code == 409, response.data


@pytest.mark.django_db
def test_get_rate_infers_inverse_when_only_reverse_pair_recorded(tenant_a):
    ExchangeRate.objects.create(
        tenant=tenant_a, from_currency="SAR", to_currency="USD", date="2026-01-01", rate="0.26667"
    )
    rate = get_rate(tenant_a, "USD", "SAR", date(2026, 1, 2))
    assert abs(rate - Decimal("3.75")) < Decimal("0.01")


@pytest.mark.django_db
def test_get_rate_still_raises_when_neither_direction_recorded(tenant_a):
    from apps.treasury.services import ExchangeRateNotFound

    with pytest.raises(ExchangeRateNotFound):
        get_rate(tenant_a, "EUR", "SAR", date(2026, 1, 1))


# ---------------------------------------------------------------------
# CFO_REVIEW_1 C16: Saudi format validation on party fields too (not
# just the company settings screen from 5.6).
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_customer_tax_number_format_validated(tenant_a, client_a):
    bad = client_a.post("/api/parties/customers/", {"name": "Bad Co", "tax_number": "12345"}, format="json")
    assert bad.status_code == 400, bad.data

    good = client_a.post(
        "/api/parties/customers/", {"name": "Good Co", "tax_number": "3" + "1" * 13 + "3"}, format="json"
    )
    assert good.status_code == 201, good.data


@pytest.mark.django_db
def test_individual_customer_national_id_format_validated(tenant_a, client_a):
    bad = client_a.post(
        "/api/parties/customers/",
        {"name": "Bad Person", "party_type": "individual", "national_id_or_cr": "999999999"},
        format="json",
    )
    assert bad.status_code == 400, bad.data

    good = client_a.post(
        "/api/parties/customers/",
        {"name": "Good Person", "party_type": "individual", "national_id_or_cr": "1234567890"},
        format="json",
    )
    assert good.status_code == 201, good.data


@pytest.mark.django_db
def test_organization_customer_cr_format_validated(tenant_a, client_a):
    bad = client_a.post(
        "/api/parties/customers/",
        {"name": "Bad Org", "party_type": "organization", "national_id_or_cr": "123"},
        format="json",
    )
    assert bad.status_code == 400, bad.data


# ---------------------------------------------------------------------
# CFO_REVIEW_1 F1: a future-dated document warns, never blocks.
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_future_dated_invoice_creation_warns_but_succeeds(tenant_a, client_a):
    from apps.organization.models import LegalEntity

    branch = LegalEntity.objects.get(tenant=tenant_a, entity_type=LegalEntity.Type.BRANCH)
    customer = client_a.post("/api/parties/customers/", {"name": "Future Co"}, format="json").data
    product = ProductFactory(tenant=tenant_a, unit_price="10.00", tax_rate="0")
    tax_code_z = TaxCode.objects.get(tenant=tenant_a, code="Z")
    future = (date.today() + timedelta(days=5)).isoformat()

    response = client_a.post(
        "/api/invoices/",
        {
            "customer": customer["id"], "legal_entity": str(branch.id), "issue_date": future,
            "lines": [{"product": str(product.id), "quantity": "1", "tax_code": str(tax_code_z.id)}],
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    assert response.data["warnings"], response.data


@pytest.mark.django_db
def test_future_dated_manual_jv_warns_but_succeeds(tenant_a, client_a):
    from apps.organization.models import LegalEntity

    branch = LegalEntity.objects.get(tenant=tenant_a, entity_type=LegalEntity.Type.BRANCH)
    cash, sales = _leaf_pair(tenant_a)
    future = (date.today() + timedelta(days=3)).isoformat()

    response = client_a.post(
        "/api/journal-entries/",
        {
            "legal_entity": str(branch.id), "date": future,
            "lines": [
                {"account": str(cash.id), "debit_fc": "5.00", "credit_fc": "0"},
                {"account": str(sales.id), "debit_fc": "0", "credit_fc": "5.00"},
            ],
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    assert response.data["warnings"], response.data


# ---------------------------------------------------------------------
# CFO_REVIEW_1 C5: general ledger endpoint, same ledger_lines() service
# as treasury movements / party statements (5.4/5.6).
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_ledger_endpoint_shows_running_balance_and_opening(tenant_a, client_a):
    from apps.organization.models import LegalEntity

    branch = LegalEntity.objects.get(tenant=tenant_a, entity_type=LegalEntity.Type.BRANCH)
    cash, sales = _leaf_pair(tenant_a)

    first = client_a.post(
        "/api/journal-entries/",
        {
            "legal_entity": str(branch.id), "date": "2026-01-01",
            "lines": [
                {"account": str(cash.id), "debit_fc": "100.00", "credit_fc": "0"},
                {"account": str(sales.id), "debit_fc": "0", "credit_fc": "100.00"},
            ],
        },
        format="json",
    )
    submit = client_a.post(f"/api/journal-entries/{first.data['id']}/submit/")
    if submit.data["status"] == "approved":
        client_a.post(f"/api/journal-entries/{first.data['id']}/post/")

    response = client_a.get(f"/api/accounts/{cash.id}/ledger/?from=2026-01-01")
    assert response.status_code == 200, response.data
    assert response.data["opening_balance"] == Decimal("0")
    assert len(response.data["lines"]) == 1
    assert response.data["closing_balance"] == Decimal("100.00")


# ---------------------------------------------------------------------
# CFO_REVIEW_1 F10: "سجل التغييرات" — a tenant's own read-only AuditLog
# window, filtered to one record.
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_tenant_audit_log_filtered_to_one_record_and_tenant_isolated(tenant_a, client_a, tenant_b):
    from apps.platform.models import AuditLog
    from apps.platform.services import log_action

    target_id = "11111111-1111-1111-1111-111111111111"
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER, actor_id=None, action="invoice.void",
        target_type="sales.Invoice", target_id=target_id, tenant_id=tenant_a.id,
    )
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER, actor_id=None, action="invoice.issue",
        target_type="sales.Invoice", target_id="22222222-2222-2222-2222-222222222222", tenant_id=tenant_a.id,
    )
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER, actor_id=None, action="invoice.void",
        target_type="sales.Invoice", target_id=target_id, tenant_id=tenant_b.id,
    )

    response = client_a.get(f"/api/audit-log/?target_type=sales.Invoice&target_id={target_id}")
    assert response.status_code == 200, response.data
    assert len(response.data["results"]) == 1
    assert response.data["results"][0]["action"] == "invoice.void"
