"""Sprint 6.8 (decision 16): PartyRole.credit_limit + TenantFeatures.
credit_limit_mode — an invoice that would push a customer's outstanding
balance over its credit limit always warns; it's only ever blocked (400
at issue()) once the tenant opts into BLOCK mode.
"""

import pytest

from apps.accounting.models import TaxCode
from apps.parties.models import PartyRole
from apps.tenants.models import TenantFeatures

from .factories import PartyFactory, ProductFactory


def _customer_with_limit(tenant, limit):
    customer = PartyFactory(tenant=tenant)
    PartyRole.objects.filter(party=customer, role=PartyRole.Role.CUSTOMER).update(credit_limit=limit)
    return customer


def _make_invoice(client, tenant, customer, amount="500.00"):
    product = ProductFactory(tenant=tenant, unit_price=amount)
    tax_code = TaxCode.objects.get(tenant=tenant, code="Z")
    response = client.post(
        "/api/invoices/",
        {
            "customer": str(customer.id), "issue_date": "2026-09-01",
            "lines": [{"product": str(product.id), "quantity": "1", "tax_code": str(tax_code.id)}],
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    return response.data


@pytest.mark.django_db
def test_invoice_over_credit_limit_warns_at_create_and_issue_in_warn_mode(tenant_a, client_a):
    customer = _customer_with_limit(tenant_a, "100.00")
    invoice = _make_invoice(client_a, tenant_a, customer, amount="500.00")
    assert any("حد الائتمان" in w for w in invoice["warnings"])

    issued = client_a.post(f"/api/invoices/{invoice['id']}/issue/")
    assert issued.status_code == 200, issued.data
    assert any("حد الائتمان" in w for w in issued.data["warnings"])


@pytest.mark.django_db
def test_invoice_over_credit_limit_blocked_in_block_mode(tenant_a, client_a):
    TenantFeatures.objects.filter(tenant_id=tenant_a.id).update(credit_limit_mode=TenantFeatures.CreditLimitMode.BLOCK)
    customer = _customer_with_limit(tenant_a, "100.00")
    invoice = _make_invoice(client_a, tenant_a, customer, amount="500.00")

    issued = client_a.post(f"/api/invoices/{invoice['id']}/issue/")
    assert issued.status_code == 400, issued.data


@pytest.mark.django_db
def test_invoice_within_credit_limit_no_warning(tenant_a, client_a):
    customer = _customer_with_limit(tenant_a, "1000.00")
    invoice = _make_invoice(client_a, tenant_a, customer, amount="100.00")
    assert invoice["warnings"] == []

    issued = client_a.post(f"/api/invoices/{invoice['id']}/issue/")
    assert issued.status_code == 200, issued.data
    assert issued.data["warnings"] == []


@pytest.mark.django_db
def test_customer_without_credit_limit_never_warns(tenant_a, client_a):
    customer = PartyFactory(tenant=tenant_a)
    invoice = _make_invoice(client_a, tenant_a, customer, amount="999999.00")
    assert invoice["warnings"] == []
