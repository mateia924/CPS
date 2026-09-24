"""Sprint 6.7 (sprint-6.md decision 14, CFO_REVIEW_1 C7): the VOID
guard — TaxPeriod FILED/PAID always blocks; a delivered invoice needs
`sales.void_delivered_invoice` + a reason; the reversal always posts
at today's date even if the invoice's own fiscal period is closed.
"""

from datetime import date

import pytest
from django.utils import timezone

from apps.access.models import Role
from apps.access.services import seed_default_roles
from apps.accounting.models import JournalEntry, TaxPeriod
from apps.accounting.periods import close_period
from apps.organization.models import LegalEntity
from apps.sales.models import Invoice

from .factories import PartyFactory, ProductFactory, UserFactory


def _roles(tenant):
    existing = {r.name: r for r in Role.objects.filter(tenant=tenant, is_system=True)}
    return existing or seed_default_roles(tenant)


def _branch(tenant):
    return LegalEntity.objects.get(tenant=tenant, entity_type=LegalEntity.Type.BRANCH)


def _make_invoice(client, tenant, issue_date="2026-09-01"):
    from apps.accounting.models import TaxCode

    customer = PartyFactory(tenant=tenant)
    product = ProductFactory(tenant=tenant, unit_price="500.00")
    tax_code = TaxCode.objects.get(tenant=tenant, code="Z")
    response = client.post(
        "/api/invoices/",
        {
            "customer": str(customer.id), "issue_date": issue_date,
            "lines": [{"product": str(product.id), "quantity": "1", "tax_code": str(tax_code.id)}],
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    issued = client.post(f"/api/invoices/{response.data['id']}/issue/")
    assert issued.status_code == 200, issued.data
    return issued.data


@pytest.mark.django_db
def test_void_rejected_409_when_tax_period_filed(tenant_a, client_a):
    invoice = _make_invoice(client_a, tenant_a, issue_date="2026-09-01")
    TaxPeriod.objects.create(
        tenant=tenant_a, legal_entity=_branch(tenant_a), period_type=TaxPeriod.PeriodType.MONTHLY,
        start=date(2026, 9, 1), end=date(2026, 9, 30), status=TaxPeriod.Status.FILED,
    )
    response = client_a.post(f"/api/invoices/{invoice['id']}/void/")
    assert response.status_code == 409, response.data


@pytest.mark.django_db
def test_void_delivered_invoice_requires_permission_and_reason(tenant_a, user_a, client_a):
    from apps.access.models import UserEntityAccess

    accountant = UserFactory(tenant=tenant_a, email="accountant@void-guard.test")
    accountant.roles.add(_roles(tenant_a)["Accountant"])
    UserEntityAccess.objects.create(user=accountant, legal_entity=_branch(tenant_a))
    from rest_framework.test import APIClient

    accountant_client = APIClient()
    accountant_client.force_authenticate(user=accountant)

    invoice = _make_invoice(client_a, tenant_a)
    Invoice.objects.filter(id=invoice["id"]).update(delivered_at="2026-09-02T10:00:00Z")

    denied = accountant_client.post(f"/api/invoices/{invoice['id']}/void/")
    assert denied.status_code == 409, denied.data

    no_reason = client_a.post(f"/api/invoices/{invoice['id']}/void/")
    assert no_reason.status_code == 409, no_reason.data

    accepted = client_a.post(f"/api/invoices/{invoice['id']}/void/", {"reason": "خطأ في الكمية"}, format="json")
    assert accepted.status_code == 200, accepted.data
    inv = Invoice.objects.get(id=invoice["id"])
    assert inv.is_post_delivery_void is True
    assert inv.status == Invoice.Status.CANCELLED


@pytest.mark.django_db
def test_void_after_period_closed_reverses_at_today(tenant_a, client_a, user_a):
    from apps.accounting.models import FiscalPeriod

    invoice = _make_invoice(client_a, tenant_a, issue_date="2026-01-15")
    period = FiscalPeriod.objects.get(fiscal_year__tenant=tenant_a, fiscal_year__name="2026", seq=1)
    close_period(period, user_a, acknowledge_warnings=True)

    response = client_a.post(f"/api/invoices/{invoice['id']}/void/")
    assert response.status_code == 200, response.data
    reversal = JournalEntry.objects.get(tenant=tenant_a, source_type="invoice_void", source_id=invoice["id"])
    assert reversal.date == timezone.localdate()
    assert reversal.status == JournalEntry.Status.POSTED


@pytest.mark.django_db
def test_tenant_isolation(tenant_a, client_a, tenant_b, client_b):
    invoice = _make_invoice(client_a, tenant_a)
    response = client_b.post(f"/api/invoices/{invoice['id']}/void/")
    assert response.status_code == 404
