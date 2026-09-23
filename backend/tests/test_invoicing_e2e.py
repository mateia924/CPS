"""Permanent pytest version of the manual curl end-to-end scenario used
during initial development: register -> login -> customer -> product ->
invoice with fully server-computed totals -> issue -> balanced journal
entry posted to the chart of accounts. docs/SYSTEM_ANALYSIS.md rules 2
(server-side money) and 4 (every journal entry balanced) apply here.

Sprint 3 (3.3): the customer step now goes through POST /api/parties/
with role=customer — the unified Party screen superseding the old
/api/customers/ endpoint as the real, current path to an invoiceable
customer (see the Decision Log on Invoice.legacy_customer).
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounting.models import TaxCode
from apps.tenants.models import Tenant


@pytest.mark.django_db
def test_register_login_customer_product_invoice_issue_balanced_journal():
    register = APIClient().post(
        "/api/auth/register/",
        {
            "company_name": "Acme Trading",
            "subdomain": "acme-e2e",
            "email": "owner@acme-e2e.test",
            "password": "S3curePass!2026",
            "first_name": "Sara",
            "last_name": "Owner",
        },
        format="json",
    )
    assert register.status_code == 201

    login = APIClient().post(
        "/api/auth/login/",
        {
            "subdomain": "acme-e2e",
            "email": "owner@acme-e2e.test",
            "password": "S3curePass!2026",
        },
        format="json",
    )
    assert login.status_code == 200

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

    customer = client.post(
        "/api/parties/",
        {"name": "Nile Retail Co", "email": "billing@nileretail.test", "role": "customer"},
        format="json",
    )
    assert customer.status_code == 201

    product1 = client.post(
        "/api/products/",
        {"sku": "SKU-001", "name": "Consulting Hour", "unit_price": "150.00", "tax_rate": "14.00"},
        format="json",
    )
    assert product1.status_code == 201

    product2 = client.post(
        "/api/products/",
        {"sku": "SKU-002", "name": "Widget", "unit_price": "40.50", "tax_rate": "14.00"},
        format="json",
    )
    assert product2.status_code == 201

    # Sprint 4.6: tax now comes from tax_code.rate (a snapshot), not
    # Product.tax_rate — "S" is the standard 15% code every tenant gets
    # at registration.
    tenant = Tenant.objects.get(subdomain="acme-e2e")
    tax_code_s = TaxCode.objects.get(tenant=tenant, code="S")

    # 3 x 150.00 + 2 x 40.50, 15% tax on each line: subtotal 531.00,
    # tax 79.65, total 610.65 — computed entirely server-side.
    invoice = client.post(
        "/api/invoices/",
        {
            "customer": customer.data["id"],
            "lines": [
                {"product": product1.data["id"], "quantity": "3", "tax_code": str(tax_code_s.id)},
                {"product": product2.data["id"], "quantity": "2", "tax_code": str(tax_code_s.id)},
            ],
        },
        format="json",
    )
    assert invoice.status_code == 201
    assert invoice.data["status"] == "draft"
    assert invoice.data["subtotal"] == "531.00"
    assert invoice.data["tax_total"] == "79.65"
    assert invoice.data["total"] == "610.65"

    issue = client.post(f"/api/invoices/{invoice.data['id']}/issue/")
    assert issue.status_code == 200
    assert issue.data["status"] == "issued"

    entries = client.get("/api/journal-entries/")
    assert entries.status_code == 200
    assert entries.data["count"] == 1

    lines = entries.data["results"][0]["lines"]
    total_debit = sum(Decimal(line["debit"]) for line in lines)
    total_credit = sum(Decimal(line["credit"]) for line in lines)
    assert total_debit == total_credit == Decimal("610.65")

    # Sprint 4.3: the AR line posts to the customer's own auto-created
    # sub-ledger account (under the CUSTOMERS system_key), not a shared
    # "1100" bucket — identified here by `party`, not a hardcoded code.
    # (str(): PrimaryKeyRelatedField's test-client `.data` value is a
    # raw UUID object, not yet stringified by the JSON renderer.)
    by_party = {str(line["party"]): line for line in lines if line["party"]}
    assert by_party[customer.data["id"]]["debit"] == "610.65"
    by_system_key = {line["account_system_key"]: line for line in lines if line.get("account_system_key")}
    assert by_system_key["SALES"]["credit"] == "531.00"
    assert by_system_key["VAT_OUTPUT"]["credit"] == "79.65"


@pytest.mark.django_db
def test_invoice_deliver_sets_delivered_at_once(tenant_a, client_a):
    """Sprint 5.6 (block 5.6, print page): the print page calls this
    fire-and-forget on load — set-once, never overwritten."""
    from apps.organization.models import LegalEntity
    from apps.sales.models import Invoice, Product

    branch = LegalEntity.objects.get(tenant=tenant_a, entity_type=LegalEntity.Type.BRANCH)
    tax_code = TaxCode.objects.get(tenant=tenant_a, code="Z")
    product = Product.objects.create(tenant=tenant_a, sku="P-DELIVER", name="Item", unit_price="50.00")
    customer = client_a.post("/api/parties/customers/", {"name": "Deliver Co"}, format="json").data

    invoice = client_a.post(
        "/api/invoices/",
        {
            "customer": customer["id"], "legal_entity": str(branch.id),
            "lines": [{"product": product.id.__str__(), "quantity": "1", "tax_code": str(tax_code.id)}],
        },
        format="json",
    ).data
    assert Invoice.objects.get(id=invoice["id"]).delivered_at is None

    first = client_a.post(f"/api/invoices/{invoice['id']}/deliver/")
    assert first.status_code == 200, first.data
    first_timestamp = Invoice.objects.get(id=invoice["id"]).delivered_at
    assert first_timestamp is not None

    second = client_a.post(f"/api/invoices/{invoice['id']}/deliver/")
    assert second.status_code == 200, second.data
    assert Invoice.objects.get(id=invoice["id"]).delivered_at == first_timestamp


@pytest.mark.django_db
def test_tax_rounds_per_line_then_sums_seven_fractional_lines(tenant_a, client_a):
    """CFO_REVIEW_1 C15: every line's tax is ROUND_HALF_UP to the cent
    independently, and the invoice's tax_total is the SUM of those
    already-rounded line amounts — never a single rounding of the
    aggregate. Seven lines with genuinely fractional (quantity ×
    unit_price) products, tax code S (15%)."""
    from decimal import ROUND_HALF_UP, Decimal

    from apps.organization.models import LegalEntity
    from apps.sales.models import Product

    branch = LegalEntity.objects.get(tenant=tenant_a, entity_type=LegalEntity.Type.BRANCH)
    tax_code = TaxCode.objects.get(tenant=tenant_a, code="S")
    customer = client_a.post("/api/parties/customers/", {"name": "Rounding Co"}, format="json").data

    line_inputs = [
        ("3.00", "10.03"), ("2.00", "7.07"), ("1.00", "19.99"), ("4.00", "3.33"),
        ("5.00", "6.66"), ("1.00", "100.01"), ("7.00", "1.11"),
    ]
    cents = Decimal("0.01")
    expected_subtotal = Decimal("0")
    expected_tax = Decimal("0")
    lines_payload = []
    for quantity, unit_price in line_inputs:
        product = Product.objects.create(
            tenant=tenant_a, sku=f"P-{unit_price}-{quantity}", name="Item", unit_price=unit_price
        )
        line_subtotal = (Decimal(quantity) * Decimal(unit_price)).quantize(cents, rounding=ROUND_HALF_UP)
        line_tax = (line_subtotal * Decimal("15.00") / Decimal("100")).quantize(cents, rounding=ROUND_HALF_UP)
        expected_subtotal += line_subtotal
        expected_tax += line_tax
        lines_payload.append({"product": str(product.id), "quantity": quantity, "tax_code": str(tax_code.id)})

    response = client_a.post(
        "/api/invoices/",
        {"customer": customer["id"], "legal_entity": str(branch.id), "lines": lines_payload},
        format="json",
    )
    assert response.status_code == 201, response.data
    assert Decimal(response.data["subtotal"]) == expected_subtotal
    assert Decimal(response.data["tax_total"]) == expected_tax
    assert Decimal(response.data["total"]) == expected_subtotal + expected_tax
