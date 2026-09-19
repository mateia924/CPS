"""Sprint 1.5 rule 3: a DRAFT invoice is freely editable; an issued
(approved) invoice is never edited, only voided — which posts a
balanced reversing journal entry (docs/SYSTEM_ANALYSIS.md section 4
rule 4: every journal entry stays balanced).
"""

from decimal import Decimal

import pytest

from .factories import PartyFactory, ProductFactory


def _create_invoice(client, customer, product, quantity="1"):
    return client.post(
        "/api/invoices/",
        {
            "customer": str(customer.id),
            "lines": [{"product": str(product.id), "quantity": quantity}],
        },
        format="json",
    )


@pytest.mark.django_db
def test_patch_draft_invoice_recalculates_totals(tenant_a, client_a):
    customer = PartyFactory(tenant=tenant_a)
    product = ProductFactory(tenant=tenant_a, unit_price="100.00", tax_rate="10.00")
    invoice = _create_invoice(client_a, customer, product, "2").data
    assert invoice["total"] == "220.00"

    response = client_a.patch(
        f"/api/invoices/{invoice['id']}/",
        {
            "customer": str(customer.id),
            "lines": [{"product": str(product.id), "quantity": "5"}],
        },
        format="json",
    )
    assert response.status_code == 200
    assert response.data["subtotal"] == "500.00"
    assert response.data["tax_total"] == "50.00"
    assert response.data["total"] == "550.00"
    assert len(response.data["lines"]) == 1
    assert response.data["lines"][0]["quantity"] == "5.00"


@pytest.mark.django_db
def test_patch_issued_invoice_rejected(tenant_a, client_a):
    customer = PartyFactory(tenant=tenant_a)
    product = ProductFactory(tenant=tenant_a)
    invoice = _create_invoice(client_a, customer, product).data
    client_a.post(f"/api/invoices/{invoice['id']}/issue/")

    response = client_a.patch(
        f"/api/invoices/{invoice['id']}/",
        {"customer": str(customer.id), "lines": [{"product": str(product.id), "quantity": "9"}]},
        format="json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_void_draft_invoice_rejected(tenant_a, client_a):
    customer = PartyFactory(tenant=tenant_a)
    product = ProductFactory(tenant=tenant_a)
    invoice = _create_invoice(client_a, customer, product).data

    response = client_a.post(f"/api/invoices/{invoice['id']}/void/")
    assert response.status_code == 400


@pytest.mark.django_db
def test_void_issued_invoice_posts_balanced_reversing_entry(tenant_a, client_a):
    customer = PartyFactory(tenant=tenant_a)
    product = ProductFactory(tenant=tenant_a, unit_price="150.00", tax_rate="14.00")
    invoice = _create_invoice(client_a, customer, product, "3").data
    client_a.post(f"/api/invoices/{invoice['id']}/issue/")

    response = client_a.post(f"/api/invoices/{invoice['id']}/void/")
    assert response.status_code == 200
    assert response.data["status"] == "cancelled"

    entries = client_a.get("/api/journal-entries/").data["results"]
    assert len(entries) == 2

    original = next(e for e in entries if e["source_type"] == "invoice")
    reversal = next(e for e in entries if e["source_type"] == "invoice_void")

    def totals(entry):
        debit = sum(Decimal(line["debit"]) for line in entry["lines"])
        credit = sum(Decimal(line["credit"]) for line in entry["lines"])
        return debit, credit

    orig_debit, orig_credit = totals(original)
    rev_debit, rev_credit = totals(reversal)
    assert orig_debit == orig_credit  # original entry itself balanced
    assert rev_debit == rev_credit  # reversal itself balanced
    assert rev_debit == orig_credit  # reversal exactly mirrors the original

    # Per-line mirroring: every original line's debit/credit is swapped
    # on the matching account in the reversal.
    orig_by_account = {line["account_code"]: line for line in original["lines"]}
    rev_by_account = {line["account_code"]: line for line in reversal["lines"]}
    assert set(orig_by_account) == set(rev_by_account)
    for code, orig_line in orig_by_account.items():
        rev_line = rev_by_account[code]
        assert rev_line["debit"] == orig_line["credit"]
        assert rev_line["credit"] == orig_line["debit"]


@pytest.mark.django_db
def test_void_already_cancelled_invoice_rejected(tenant_a, client_a):
    customer = PartyFactory(tenant=tenant_a)
    product = ProductFactory(tenant=tenant_a)
    invoice = _create_invoice(client_a, customer, product).data
    client_a.post(f"/api/invoices/{invoice['id']}/issue/")
    client_a.post(f"/api/invoices/{invoice['id']}/void/")

    response = client_a.post(f"/api/invoices/{invoice['id']}/void/")
    assert response.status_code == 400
