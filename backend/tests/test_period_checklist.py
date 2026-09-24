"""Sprint 6.7 (docs/SYSTEM_ANALYSIS.md 3.9, sprint-6.md decision 13):
the real period-close checklist — replaces block 6.1's simplified
check. Real HTTP API + real Postgres throughout.
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.access.models import Role
from apps.access.services import seed_default_roles
from apps.accounting.models import Account, FiscalPeriod
from apps.accounting.recurring import generate_due_installments
from apps.approvals.models import ApprovalRule
from apps.organization.models import LegalEntity
from apps.treasury.models import BankStatement

from .factories import PartyFactory, ProductFactory


def _roles(tenant):
    existing = {r.name: r for r in Role.objects.filter(tenant=tenant, is_system=True)}
    return existing or seed_default_roles(tenant)


def _branch(tenant):
    return LegalEntity.objects.get(tenant=tenant, entity_type=LegalEntity.Type.BRANCH)


def _period(tenant, seq, year="2026"):
    return FiscalPeriod.objects.get(fiscal_year__tenant=tenant, fiscal_year__name=year, seq=seq)


def _seed_recurring_rule(tenant):
    owner_role = _roles(tenant)["Owner"]
    return ApprovalRule.objects.get_or_create(
        tenant=tenant, doc_type=ApprovalRule.DocType.RECURRING_ENTRY, min_amount=0,
        defaults={"required_role": owner_role, "is_active": True},
    )[0]


def _make_bank(client, tenant, currency="SAR"):
    response = client.post(
        "/api/banks/", {"legal_entity": str(_branch(tenant).id), "name": "Bank", "currency": currency}, format="json"
    )
    assert response.status_code == 201, response.data
    return response.data


@pytest.mark.django_db
def test_draft_invoice_blocks_checklist_and_close(tenant_a, client_a):
    customer = PartyFactory(tenant=tenant_a)
    product = ProductFactory(tenant=tenant_a, unit_price="100.00")
    from apps.accounting.models import TaxCode

    tax_code = TaxCode.objects.get(tenant=tenant_a, code="Z")
    created = client_a.post(
        "/api/invoices/",
        {
            "customer": str(customer.id), "issue_date": "2026-01-15",
            "lines": [{"product": str(product.id), "quantity": "1", "tax_code": str(tax_code.id)}],
        },
        format="json",
    )
    assert created.status_code == 201, created.data

    period = _period(tenant_a, 1)
    checklist = client_a.get(f"/api/fiscal-periods/{period.id}/checklist/")
    codes = [item["code"] for item in checklist.data["items"]]
    assert "unposted_documents" in codes
    block_item = next(item for item in checklist.data["items"] if item["code"] == "unposted_documents")
    assert created.data["id"] in [ref["id"] for ref in block_item["references"]]

    close = client_a.post(f"/api/fiscal-periods/{period.id}/close/", {"acknowledge_warnings": True}, format="json")
    assert close.status_code == 400, close.data


@pytest.mark.django_db
def test_due_installment_blocks_then_generating_clears_it(tenant_a, client_a, user_a):
    _seed_recurring_rule(tenant_a)
    entity = _branch(tenant_a)
    cash = Account.objects.get(tenant=tenant_a, system_key="CASH")
    sales = Account.objects.get(tenant=tenant_a, system_key="SALES")

    created = client_a.post(
        "/api/recurring-entries/",
        {
            "legal_entity": str(entity.id), "kind": "prepaid_expense", "description": "test",
            "from_account": str(cash.id), "to_account": str(sales.id),
            "total_amount_base": "1200", "installments_count": 1,
            "first_period": str(_period(tenant_a, 1).id),
        },
        format="json",
    )
    assert created.status_code == 201, created.data
    client_a.post(f"/api/recurring-entries/{created.data['id']}/submit/")
    client_a.post(f"/api/recurring-entries/{created.data['id']}/approve/")

    period = _period(tenant_a, 1)
    checklist = client_a.get(f"/api/fiscal-periods/{period.id}/checklist/")
    codes = [item["code"] for item in checklist.data["items"]]
    assert "recurring_installments_due" in codes

    generate_due_installments(tenant=tenant_a, as_of=period.end_date)

    checklist_after = client_a.get(f"/api/fiscal-periods/{period.id}/checklist/")
    codes_after = [item["code"] for item in checklist_after.data["items"]]
    assert "recurring_installments_due" not in codes_after


@pytest.mark.django_db
def test_bank_out_of_balance_warns_and_requires_acknowledgment(tenant_a, client_a):
    bank = _make_bank(client_a, tenant_a)
    BankStatement.objects.create(
        tenant=tenant_a, bank_id=bank["id"], period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
        currency="SAR", closing_balance=Decimal("1000.00"),
    )
    period = _period(tenant_a, 1)

    checklist = client_a.get(f"/api/fiscal-periods/{period.id}/checklist/")
    codes = [item["code"] for item in checklist.data["items"]]
    assert "bank_not_reconciled" in codes

    rejected = client_a.post(f"/api/fiscal-periods/{period.id}/close/", {}, format="json")
    assert rejected.status_code == 400, rejected.data

    closed = client_a.post(f"/api/fiscal-periods/{period.id}/close/", {"acknowledge_warnings": True}, format="json")
    assert closed.status_code == 200, closed.data
    period.refresh_from_db()
    assert period.status == FiscalPeriod.Status.CLOSED
    snapshot_codes = [item["code"] for item in period.close_snapshot["items"]]
    assert "bank_not_reconciled" in snapshot_codes


@pytest.mark.django_db
def test_tenant_isolation(tenant_a, client_a, tenant_b, client_b):
    period_a = _period(tenant_a, 1)
    period_b = _period(tenant_b, 1)
    response = client_b.get(f"/api/fiscal-periods/{period_a.id}/checklist/")
    assert response.status_code == 404
    assert client_a.get(f"/api/fiscal-periods/{period_b.id}/checklist/").status_code == 404
