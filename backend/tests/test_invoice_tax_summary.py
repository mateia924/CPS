"""Block 8.2.1: the tax invoice's tax-by-code table is summed on the server.

The printed invoice used to add `parseFloat(line.line_subtotal)` /
`parseFloat(line.line_tax)` in the browser. A 72-line invoice of awkward
amounts printed the right cents (2448.30 / 240.67), but the browser held
844.0200000000002 and 1604.2799999999997 before formatting. A legal VAT
document is not totalled in float arithmetic, so the API now sends
`tax_summary`, summed in Decimal from the lines' own rounded figures, and
the print page renders it as is.
"""

from collections import defaultdict
from decimal import Decimal

import pytest

from apps.accounting.models import TaxCode

from .factories import PartyFactory, ProductFactory
from .test_vouchers import _branch

PRICES = ["0.10", "0.07", "33.33", "0.01", "1.15", "19.99"]
QUANTITIES = ["1", "3", "7", "0.33", "11", "0.07"]


@pytest.mark.django_db
def test_tax_summary_is_the_decimal_sum_of_the_lines_and_adds_up_to_the_invoice(tenant_a, client_a):
    customer = PartyFactory(tenant=tenant_a)
    standard = TaxCode.objects.get(tenant=tenant_a, code="S")
    zero = TaxCode.objects.get(tenant=tenant_a, code="Z")
    products = [ProductFactory(tenant=tenant_a, unit_price=price) for price in PRICES]
    lines = [
        {"product": str(product.id), "quantity": quantity, "tax_code": str((zero if (p + q + k) % 3 == 0 else standard).id)}
        for k in range(2)
        for p, product in enumerate(products)
        for q, quantity in enumerate(QUANTITIES)
    ]
    created = client_a.post(
        "/api/invoices/",
        {"customer": str(customer.id), "legal_entity": str(_branch(tenant_a).id), "lines": lines},
        format="json",
    )
    assert created.status_code == 201, created.data
    invoice = client_a.get(f"/api/invoices/{created.data['id']}/").data
    assert len(invoice["lines"]) == 72

    expected = defaultdict(lambda: [Decimal("0"), Decimal("0")])
    for line in invoice["lines"]:
        expected[(line["tax_code_display"], line["tax_rate"])][0] += Decimal(line["line_subtotal"])
        expected[(line["tax_code_display"], line["tax_rate"])][1] += Decimal(line["line_tax"])

    summary = invoice["tax_summary"]
    assert {(row["code"], row["rate"]) for row in summary} == set(expected)
    for row in summary:
        base, tax = expected[(row["code"], row["rate"])]
        # Exact strings: Decimal sums of 2-place values keep 2 places; a
        # float sum would surface as 844.0200000000002.
        assert row["base"] == str(base), row
        assert row["tax"] == str(tax), row
    assert sum(Decimal(row["base"]) for row in summary) == Decimal(invoice["subtotal"])
    assert sum(Decimal(row["tax"]) for row in summary) == Decimal(invoice["tax_total"])
    assert (invoice["subtotal"], invoice["tax_total"]) == ("2448.30", "240.67")


@pytest.mark.django_db
def test_lines_of_one_code_at_two_rates_are_two_rows(tenant_a, client_a):
    """The browser grouped by code alone and labelled the row with the
    first line's rate. A rate change mid-invoice (a code's rate edited
    between lines' snapshots) must not merge into one mislabelled row."""
    from apps.sales.models import InvoiceLine

    customer = PartyFactory(tenant=tenant_a)
    standard = TaxCode.objects.get(tenant=tenant_a, code="S")
    product = ProductFactory(tenant=tenant_a, unit_price="100.00")
    created = client_a.post(
        "/api/invoices/",
        {
            "customer": str(customer.id), "legal_entity": str(_branch(tenant_a).id),
            "lines": [{"product": str(product.id), "quantity": "1", "tax_code": str(standard.id)}] * 2,
        },
        format="json",
    )
    assert created.status_code == 201, created.data
    first = InvoiceLine.objects.filter(invoice_id=created.data["id"]).first()
    InvoiceLine.objects.filter(pk=first.pk).update(tax_rate=Decimal("5.00"), line_tax=Decimal("5.00"))
    summary = client_a.get(f"/api/invoices/{created.data['id']}/").data["tax_summary"]
    assert sorted((row["rate"], row["tax"]) for row in summary) == [("15.00", "15.00"), ("5.00", "5.00")]
