"""Permanent pytest version of the manual curl end-to-end scenario used
during initial development: register -> login -> customer -> product ->
invoice with fully server-computed totals -> issue -> balanced journal
entry posted to the chart of accounts. docs/SYSTEM_ANALYSIS.md rules 2
(server-side money) and 4 (every journal entry balanced) apply here.
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient


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
        "/api/customers/",
        {"name": "Nile Retail Co", "email": "billing@nileretail.test"},
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

    # 3 x 150.00 + 2 x 40.50, 14% tax on each line: subtotal 531.00,
    # tax 74.34, total 605.34 — computed entirely server-side.
    invoice = client.post(
        "/api/invoices/",
        {
            "customer": customer.data["id"],
            "lines": [
                {"product": product1.data["id"], "quantity": "3"},
                {"product": product2.data["id"], "quantity": "2"},
            ],
        },
        format="json",
    )
    assert invoice.status_code == 201
    assert invoice.data["status"] == "draft"
    assert invoice.data["subtotal"] == "531.00"
    assert invoice.data["tax_total"] == "74.34"
    assert invoice.data["total"] == "605.34"

    issue = client.post(f"/api/invoices/{invoice.data['id']}/issue/")
    assert issue.status_code == 200
    assert issue.data["status"] == "issued"

    entries = client.get("/api/journal-entries/")
    assert entries.status_code == 200
    assert entries.data["count"] == 1

    lines = entries.data["results"][0]["lines"]
    total_debit = sum(Decimal(line["debit"]) for line in lines)
    total_credit = sum(Decimal(line["credit"]) for line in lines)
    assert total_debit == total_credit == Decimal("605.34")

    by_code = {line["account_code"]: line for line in lines}
    assert by_code["1100"]["debit"] == "605.34"  # Accounts Receivable
    assert by_code["4000"]["credit"] == "531.00"  # Sales Revenue
    assert by_code["2100"]["credit"] == "74.34"  # Tax Payable
