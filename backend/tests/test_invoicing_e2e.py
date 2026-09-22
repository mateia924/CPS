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

    # Sprint 4.3: the AR line posts to the customer's own auto-created
    # sub-ledger account (under the CUSTOMERS system_key), not a shared
    # "1100" bucket — identified here by `party`, not a hardcoded code.
    # (str(): PrimaryKeyRelatedField's test-client `.data` value is a
    # raw UUID object, not yet stringified by the JSON renderer.)
    by_party = {str(line["party"]): line for line in lines if line["party"]}
    assert by_party[customer.data["id"]]["debit"] == "605.34"
    by_system_key = {line["account_system_key"]: line for line in lines if line.get("account_system_key")}
    assert by_system_key["SALES"]["credit"] == "531.00"
    assert by_system_key["VAT_OUTPUT"]["credit"] == "74.34"
