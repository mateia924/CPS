"""Sprint 5.3 (docs/SYSTEM_ANALYSIS.md 3.8): the voucher engine —
receipt/payment, invoice allocation, realized FX, treasury balance
checks. Driven through the real HTTP API end to end (register a bank,
issue a real invoice, pay it) against real Postgres, matching this
project's testing philosophy throughout.
"""

from decimal import Decimal

import pytest

from apps.accounting.models import Account, JournalEntry
from apps.organization.models import LegalEntity
from apps.sales.models import Invoice
from apps.treasury.models import ExchangeRate

from .factories import PartyFactory, ProductFactory


def _branch(tenant):
    return LegalEntity.objects.get(tenant=tenant, entity_type=LegalEntity.Type.BRANCH)


def _make_bank(client, tenant, currency="SAR"):
    response = client.post(
        "/api/banks/",
        {"legal_entity": str(_branch(tenant).id), "name": f"Bank {currency}", "currency": currency},
        format="json",
    )
    assert response.status_code == 201, response.data
    return response.data


def _make_cash_box(client, tenant, max_balance=None):
    payload = {"legal_entity": str(_branch(tenant).id), "name": "Cash box", "currency": "SAR"}
    if max_balance is not None:
        payload["max_balance"] = max_balance
    response = client.post("/api/cash-boxes/", payload, format="json")
    assert response.status_code == 201, response.data
    return response.data


def _make_invoice(client, tenant, customer, currency=None, exchange_rate=None, tax_code_code="Z", amount="1000.00"):
    product = ProductFactory(tenant=tenant, unit_price=amount)
    from apps.accounting.models import TaxCode

    tax_code = TaxCode.objects.get(tenant=tenant, code=tax_code_code)
    payload = {
        "customer": str(customer.id),
        "legal_entity": str(_branch(tenant).id),
        "lines": [{"product": str(product.id), "quantity": "1", "tax_code": str(tax_code.id)}],
    }
    if currency:
        payload["currency"] = currency
    if exchange_rate:
        payload["exchange_rate"] = str(exchange_rate)
    response = client.post("/api/invoices/", payload, format="json")
    assert response.status_code == 201, response.data
    invoice_id = response.data["id"]
    issue = client.post(f"/api/invoices/{invoice_id}/issue/")
    assert issue.status_code == 200, issue.data
    return issue.data


def _create_voucher(client, **payload):
    response = client.post("/api/vouchers/", payload, format="json")
    return response


def _post(client, voucher_id):
    return client.post(f"/api/vouchers/{voucher_id}/post/")


def _fund_cash_box(client, tenant, cash_box, amount="1000.00"):
    """A RECEIPT voucher with a direct ACCOUNT line (against some
    revenue account) so `cash_box` has a real, posted balance before a
    test exercises the payment side — _balance_warnings_and_checks hard
    -blocks a cash-box/custody payment that would go negative, so every
    payment-side scenario below needs funds in the box first."""
    from apps.accounting.models import Account, TaxCode

    revenue = Account.objects.filter(tenant=tenant, code="4100").first()
    tax_code = TaxCode.objects.get(tenant=tenant, code="Z")
    response = _create_voucher(
        client,
        voucher_type="receipt",
        legal_entity=str(_branch(tenant).id),
        date="2026-09-23",
        treasury_kind="cash_box",
        treasury_id=cash_box["id"],
        payee_name="Funding",
        lines=[{"line_type": "account", "account": str(revenue.id), "tax_code": str(tax_code.id), "amount_fc": amount}],
    )
    assert response.status_code == 201, response.data
    posted = _post(client, response.data["id"])
    assert posted.status_code == 200, posted.data


@pytest.mark.django_db
def test_receipt_settles_sar_invoice_fully(tenant_a, client_a):
    customer = PartyFactory(tenant=tenant_a)
    bank = _make_bank(client_a, tenant_a)
    invoice = _make_invoice(client_a, tenant_a, customer, tax_code_code="S")
    assert invoice["total"] == "1150.00"

    response = _create_voucher(
        client_a,
        voucher_type="receipt",
        legal_entity=str(_branch(tenant_a).id),
        date="2026-09-23",
        treasury_kind="bank",
        treasury_id=bank["id"],
        party=str(customer.id),
        party_role="customer",
        lines=[{"line_type": "invoice", "invoice": invoice["id"], "amount_fc": "1150.00", "allocated_invoice_fc": "1150.00"}],
    )
    assert response.status_code == 201, response.data
    voucher = _post(client_a, response.data["id"])
    assert voucher.status_code == 200, voucher.data
    voucher = voucher.data
    assert voucher["status"] == "posted"
    assert voucher["number"]

    inv = Invoice.objects.get(id=invoice["id"])
    assert inv.status == Invoice.Status.PAID
    assert inv.balance_fc == Decimal("0.00")
    assert inv.paid_fc == Decimal("1150.00")
    assert voucher["journal_entry_id"] is not None

    entry = JournalEntry.objects.get(id=voucher["journal_entry_id"])
    debit_total = sum((line.debit for line in entry.lines.all()), Decimal("0"))
    credit_total = sum((line.credit for line in entry.lines.all()), Decimal("0"))
    assert debit_total == credit_total == Decimal("1150.00")


@pytest.mark.django_db
def test_receipt_usd_invoice_from_usd_bank_realizes_fx_gain(tenant_a, client_a):
    ExchangeRate.objects.create(tenant=tenant_a, from_currency="USD", to_currency="SAR", date="2026-09-01", rate="3.75")
    customer = PartyFactory(tenant=tenant_a)
    bank = _make_bank(client_a, tenant_a, currency="USD")
    invoice = _make_invoice(client_a, tenant_a, customer, currency="USD", tax_code_code="Z", amount="1000.00")
    assert invoice["exchange_rate"] == "3.75000000"
    assert invoice["total"] == "1000.00"

    ExchangeRate.objects.create(tenant=tenant_a, from_currency="USD", to_currency="SAR", date="2026-09-23", rate="3.80")

    response = _create_voucher(
        client_a,
        voucher_type="receipt",
        legal_entity=str(_branch(tenant_a).id),
        date="2026-09-23",
        treasury_kind="bank",
        treasury_id=bank["id"],
        party=str(customer.id),
        party_role="customer",
        lines=[{"line_type": "invoice", "invoice": invoice["id"], "amount_fc": "1000.00", "allocated_invoice_fc": "1000.00"}],
    )
    assert response.status_code == 201, response.data
    voucher = _post(client_a, response.data["id"])
    assert voucher.status_code == 200, voucher.data
    voucher = voucher.data

    entry = JournalEntry.objects.get(id=voucher["journal_entry_id"])
    debit_total = sum((line.debit for line in entry.lines.all()), Decimal("0"))
    credit_total = sum((line.credit for line in entry.lines.all()), Decimal("0"))
    assert debit_total == credit_total

    fx_account = Account.objects.get(tenant=tenant_a, system_key="FX_REALIZED")
    fx_line = entry.lines.get(account=fx_account)
    assert fx_line.credit == Decimal("50.00")
    assert fx_line.debit == Decimal("0.00")

    bank_gl = Account.objects.get(tenant=tenant_a, id=Account.objects.get(tenant=tenant_a, system_key="BANKS").children.first().id)
    bank_line = entry.lines.get(account=bank_gl)
    assert bank_line.debit_fc == Decimal("1000.00")
    assert bank_line.debit == Decimal("3800.00")

    inv = Invoice.objects.get(id=invoice["id"])
    assert inv.paid_fc == Decimal("1000.00")
    assert inv.status == Invoice.Status.PAID


@pytest.mark.django_db
def test_receipt_usd_invoice_settled_from_sar_bank_realizes_fx_gain(tenant_a, client_a):
    ExchangeRate.objects.create(tenant=tenant_a, from_currency="USD", to_currency="SAR", date="2026-09-01", rate="3.75")
    customer = PartyFactory(tenant=tenant_a)
    bank = _make_bank(client_a, tenant_a, currency="SAR")
    invoice = _make_invoice(client_a, tenant_a, customer, currency="USD", tax_code_code="Z", amount="1000.00")
    assert invoice["total"] == "1000.00"

    response = _create_voucher(
        client_a,
        voucher_type="receipt",
        legal_entity=str(_branch(tenant_a).id),
        date="2026-09-23",
        treasury_kind="bank",
        treasury_id=bank["id"],
        party=str(customer.id),
        party_role="customer",
        lines=[{"line_type": "invoice", "invoice": invoice["id"], "amount_fc": "3790.00", "allocated_invoice_fc": "1000.00"}],
    )
    assert response.status_code == 201, response.data
    voucher = _post(client_a, response.data["id"])
    assert voucher.status_code == 200, voucher.data
    voucher = voucher.data

    entry = JournalEntry.objects.get(id=voucher["journal_entry_id"])
    fx_account = Account.objects.get(tenant=tenant_a, system_key="FX_REALIZED")
    fx_line = entry.lines.get(account=fx_account)
    assert fx_line.credit == Decimal("40.00")

    inv = Invoice.objects.get(id=invoice["id"])
    assert inv.status == Invoice.Status.PAID


@pytest.mark.django_db
def test_partial_allocation_leaves_invoice_partial(tenant_a, client_a):
    ExchangeRate.objects.create(tenant=tenant_a, from_currency="USD", to_currency="SAR", date="2026-09-01", rate="3.75")
    customer = PartyFactory(tenant=tenant_a)
    bank = _make_bank(client_a, tenant_a, currency="USD")
    invoice = _make_invoice(client_a, tenant_a, customer, currency="USD", tax_code_code="Z", amount="1000.00")

    response = _create_voucher(
        client_a,
        voucher_type="receipt",
        legal_entity=str(_branch(tenant_a).id),
        date="2026-09-01",
        treasury_kind="bank",
        treasury_id=bank["id"],
        party=str(customer.id),
        party_role="customer",
        lines=[{"line_type": "invoice", "invoice": invoice["id"], "amount_fc": "400.00", "allocated_invoice_fc": "400.00"}],
    )
    assert response.status_code == 201, response.data
    voucher = _post(client_a, response.data["id"])
    assert voucher.status_code == 200, voucher.data

    inv = Invoice.objects.get(id=invoice["id"])
    assert inv.paid_fc == Decimal("400.00")
    assert inv.balance_fc == Decimal("600.00")
    assert inv.payment_status == Invoice.PaymentStatus.PARTIAL
    assert inv.status == Invoice.Status.ISSUED


@pytest.mark.django_db
def test_over_allocation_rejected(tenant_a, client_a):
    customer = PartyFactory(tenant=tenant_a)
    bank = _make_bank(client_a, tenant_a)
    invoice = _make_invoice(client_a, tenant_a, customer, tax_code_code="Z", amount="1000.00")

    response = _create_voucher(
        client_a,
        voucher_type="receipt",
        legal_entity=str(_branch(tenant_a).id),
        date="2026-09-23",
        treasury_kind="bank",
        treasury_id=bank["id"],
        party=str(customer.id),
        party_role="customer",
        lines=[{"line_type": "invoice", "invoice": invoice["id"], "amount_fc": "2000.00", "allocated_invoice_fc": "2000.00"}],
    )
    assert response.status_code == 400, response.data


@pytest.mark.django_db
def test_voucher_currency_pinned_to_treasury_currency_mismatch_is_400(tenant_a, client_a):
    ExchangeRate.objects.create(tenant=tenant_a, from_currency="EUR", to_currency="SAR", date="2026-09-01", rate="4.10")
    customer = PartyFactory(tenant=tenant_a)
    bank = _make_bank(client_a, tenant_a, currency="USD")
    invoice = _make_invoice(client_a, tenant_a, customer, currency="EUR", tax_code_code="Z", amount="500.00")

    response = _create_voucher(
        client_a,
        voucher_type="receipt",
        legal_entity=str(_branch(tenant_a).id),
        date="2026-09-23",
        treasury_kind="bank",
        treasury_id=bank["id"],
        party=str(customer.id),
        party_role="customer",
        lines=[{"line_type": "invoice", "invoice": invoice["id"], "amount_fc": "500.00", "allocated_invoice_fc": "500.00"}],
    )
    assert response.status_code == 400, response.data


@pytest.mark.django_db
def test_payment_voucher_account_line_with_deductible_tax_splits_vat_input(tenant_a, client_a):
    from apps.accounting.models import TaxCode

    cash_box = _make_cash_box(client_a, tenant_a)
    _fund_cash_box(client_a, tenant_a, cash_box)
    fuel_expense = Account.objects.filter(tenant=tenant_a, code="5100").first()
    tax_code = TaxCode.objects.get(tenant=tenant_a, code="S")

    response = _create_voucher(
        client_a,
        voucher_type="payment",
        legal_entity=str(_branch(tenant_a).id),
        date="2026-09-23",
        treasury_kind="cash_box",
        treasury_id=cash_box["id"],
        payee_name="Gas station",
        lines=[
            {
                "line_type": "account", "account": str(fuel_expense.id), "tax_code": str(tax_code.id),
                "amount_includes_tax": True, "amount_fc": "115.00",
            }
        ],
    )
    assert response.status_code == 201, response.data
    voucher = _post(client_a, response.data["id"])
    assert voucher.status_code == 200, voucher.data
    voucher = voucher.data

    entry = JournalEntry.objects.get(id=voucher["journal_entry_id"])
    lines = list(entry.lines.all())
    vat_input = Account.objects.get(tenant=tenant_a, system_key="VAT_INPUT")
    vat_line = entry.lines.get(account=vat_input)
    assert vat_line.debit == Decimal("15.00")
    expense_line = entry.lines.get(account=fuel_expense)
    assert expense_line.debit == Decimal("100.00")
    debit_total = sum((line.debit for line in lines), Decimal("0"))
    credit_total = sum((line.credit for line in lines), Decimal("0"))
    assert debit_total == credit_total == Decimal("115.00")


@pytest.mark.django_db
def test_payment_voucher_non_deductible_tax_folds_into_expense_no_tax_line(tenant_a, client_a):
    from apps.accounting.models import TaxCode

    cash_box = _make_cash_box(client_a, tenant_a)
    _fund_cash_box(client_a, tenant_a, cash_box)
    expense = Account.objects.filter(tenant=tenant_a, code="5100").first()
    tax_code = TaxCode.objects.get(tenant=tenant_a, code="SN")

    response = _create_voucher(
        client_a,
        voucher_type="payment",
        legal_entity=str(_branch(tenant_a).id),
        date="2026-09-23",
        treasury_kind="cash_box",
        treasury_id=cash_box["id"],
        payee_name="Vendor",
        lines=[
            {
                "line_type": "account", "account": str(expense.id), "tax_code": str(tax_code.id),
                "amount_includes_tax": True, "amount_fc": "115.00",
            }
        ],
    )
    assert response.status_code == 201, response.data
    voucher = _post(client_a, response.data["id"])
    assert voucher.status_code == 200, voucher.data
    voucher = voucher.data

    entry = JournalEntry.objects.get(id=voucher["journal_entry_id"])
    lines = list(entry.lines.all())
    assert len(lines) == 2
    expense_line = entry.lines.get(account=expense)
    assert expense_line.debit == Decimal("115.00")


@pytest.mark.django_db
def test_payment_voucher_reverse_charge_posts_two_equal_lines(tenant_a, client_a):
    from apps.accounting.models import TaxCode

    cash_box = _make_cash_box(client_a, tenant_a)
    _fund_cash_box(client_a, tenant_a, cash_box)
    expense = Account.objects.filter(tenant=tenant_a, code="5100").first()
    tax_code = TaxCode.objects.get(tenant=tenant_a, code="RC")

    response = _create_voucher(
        client_a,
        voucher_type="payment",
        legal_entity=str(_branch(tenant_a).id),
        date="2026-09-23",
        treasury_kind="cash_box",
        treasury_id=cash_box["id"],
        payee_name="Foreign vendor",
        lines=[
            {
                "line_type": "account", "account": str(expense.id), "tax_code": str(tax_code.id),
                "amount_includes_tax": False, "amount_fc": "100.00",
            }
        ],
    )
    assert response.status_code == 201, response.data
    voucher = _post(client_a, response.data["id"])
    assert voucher.status_code == 200, voucher.data
    voucher = voucher.data

    entry = JournalEntry.objects.get(id=voucher["journal_entry_id"])
    vat_output = Account.objects.get(tenant=tenant_a, system_key="VAT_OUTPUT")
    vat_input = Account.objects.get(tenant=tenant_a, system_key="VAT_INPUT")
    output_line = entry.lines.get(account=vat_output)
    input_line = entry.lines.get(account=vat_input)
    assert output_line.credit == input_line.debit == Decimal("15.00")


@pytest.mark.django_db
def test_payment_sufficiency_checked_as_of_the_vouchers_own_date_not_today(tenant_a, client_a):
    """Sprint 6.5.18 (UAT item 6): a payment dated 2026-09-26 against a
    cash box that only received its funding on 2026-09-30 must be
    rejected — the box's own running balance on the 26th was still 0,
    even though "today" (after the later funding) it looks sufficient.
    The rejection message must name the balance and the shortfall."""
    from apps.accounting.models import Account, TaxCode

    cash_box = _make_cash_box(client_a, tenant_a)
    revenue = Account.objects.filter(tenant=tenant_a, code="4100").first()
    expense = Account.objects.filter(tenant=tenant_a, code="5100").first()
    tax_code = TaxCode.objects.get(tenant=tenant_a, code="Z")

    funding = _create_voucher(
        client_a,
        voucher_type="receipt",
        legal_entity=str(_branch(tenant_a).id),
        date="2026-09-30",
        treasury_kind="cash_box",
        treasury_id=cash_box["id"],
        payee_name="Funding",
        lines=[{"line_type": "account", "account": str(revenue.id), "tax_code": str(tax_code.id), "amount_fc": "12000.00"}],
    )
    assert funding.status_code == 201, funding.data
    posted_funding = _post(client_a, funding.data["id"])
    assert posted_funding.status_code == 200, posted_funding.data

    response = _create_voucher(
        client_a,
        voucher_type="payment",
        legal_entity=str(_branch(tenant_a).id),
        date="2026-09-26",
        treasury_kind="cash_box",
        treasury_id=cash_box["id"],
        payee_name="Vendor",
        lines=[{"line_type": "account", "account": str(expense.id), "tax_code": str(tax_code.id), "amount_fc": "500.00"}],
    )
    assert response.status_code == 201, response.data
    voucher = _post(client_a, response.data["id"])
    assert voucher.status_code == 400, voucher.data
    detail = voucher.data["detail"]
    message = " ".join(detail) if isinstance(detail, list) else detail
    assert "0.00" in message  # the box's own balance on the 26th
    assert "500.00" in message  # the shortfall


def test_payment_exceeding_cash_box_balance_is_rejected(tenant_a, client_a):
    cash_box = _make_cash_box(client_a, tenant_a)
    expense = Account.objects.filter(tenant=tenant_a, code="5100").first()
    from apps.accounting.models import TaxCode

    tax_code = TaxCode.objects.get(tenant=tenant_a, code="Z")

    response = _create_voucher(
        client_a,
        voucher_type="payment",
        legal_entity=str(_branch(tenant_a).id),
        date="2026-09-23",
        treasury_kind="cash_box",
        treasury_id=cash_box["id"],
        payee_name="Vendor",
        lines=[{"line_type": "account", "account": str(expense.id), "tax_code": str(tax_code.id), "amount_fc": "500.00"}],
    )
    assert response.status_code == 201, response.data
    voucher = _post(client_a, response.data["id"])
    assert voucher.status_code == 400, voucher.data


@pytest.mark.django_db
def test_payment_from_bank_with_no_balance_allowed_with_warning(tenant_a, client_a):
    bank = _make_bank(client_a, tenant_a)
    expense = Account.objects.filter(tenant=tenant_a, code="5100").first()
    from apps.accounting.models import TaxCode

    tax_code = TaxCode.objects.get(tenant=tenant_a, code="Z")

    response = _create_voucher(
        client_a,
        voucher_type="payment",
        legal_entity=str(_branch(tenant_a).id),
        date="2026-09-23",
        treasury_kind="bank",
        treasury_id=bank["id"],
        payee_name="X",
        lines=[{"line_type": "account", "account": str(expense.id), "tax_code": str(tax_code.id), "amount_fc": "10.00"}],
    )
    assert response.status_code == 201, response.data
    voucher = _post(client_a, response.data["id"])
    assert voucher.status_code == 200, voucher.data
    assert voucher.data["warnings"], voucher.data
    assert voucher.data["status"] == "posted"


@pytest.mark.django_db
def test_receipt_exceeding_cash_box_max_balance_warns_but_posts(tenant_a, client_a):
    customer = PartyFactory(tenant=tenant_a)
    cash_box = _make_cash_box(client_a, tenant_a, max_balance="500.00")
    invoice = _make_invoice(client_a, tenant_a, customer, tax_code_code="Z", amount="1000.00")

    response = _create_voucher(
        client_a,
        voucher_type="receipt",
        legal_entity=str(_branch(tenant_a).id),
        date="2026-09-23",
        treasury_kind="cash_box",
        treasury_id=cash_box["id"],
        party=str(customer.id),
        party_role="customer",
        lines=[{"line_type": "invoice", "invoice": invoice["id"], "amount_fc": "1000.00", "allocated_invoice_fc": "1000.00"}],
    )
    assert response.status_code == 201, response.data
    voucher = _post(client_a, response.data["id"])
    assert voucher.status_code == 200, voucher.data
    assert voucher.data["warnings"], voucher.data


@pytest.mark.django_db
def test_reverse_voucher_restores_invoice_and_treasury_balance(tenant_a, client_a):
    customer = PartyFactory(tenant=tenant_a)
    bank = _make_bank(client_a, tenant_a)
    invoice = _make_invoice(client_a, tenant_a, customer, tax_code_code="Z", amount="1000.00")

    response = _create_voucher(
        client_a,
        voucher_type="receipt",
        legal_entity=str(_branch(tenant_a).id),
        date="2026-09-23",
        treasury_kind="bank",
        treasury_id=bank["id"],
        party=str(customer.id),
        party_role="customer",
        lines=[{"line_type": "invoice", "invoice": invoice["id"], "amount_fc": "1000.00", "allocated_invoice_fc": "1000.00"}],
    )
    voucher = _post(client_a, response.data["id"]).data
    inv = Invoice.objects.get(id=invoice["id"])
    assert inv.status == Invoice.Status.PAID

    reverse = client_a.post(f"/api/vouchers/{voucher['id']}/reverse/", {"reason": "wrong amount"}, format="json")
    assert reverse.status_code == 200, reverse.data
    assert reverse.data["status"] == "reversed"

    inv.refresh_from_db()
    assert inv.status == Invoice.Status.ISSUED
    assert inv.balance_fc == Decimal("1000.00")
    assert inv.paid_fc == Decimal("0.00")

    entry = JournalEntry.objects.get(id=voucher["journal_entry_id"])
    assert entry.status == JournalEntry.Status.REVERSED


@pytest.mark.django_db
def test_on_account_line_debits_employee_account(tenant_a, client_a):
    from apps.parties.models import PartyRole

    employee = PartyFactory(tenant=tenant_a)
    PartyRole.objects.create(party=employee, role=PartyRole.Role.EMPLOYEE)
    cash_box = _make_cash_box(client_a, tenant_a)
    _fund_cash_box(client_a, tenant_a, cash_box)

    response = _create_voucher(
        client_a,
        voucher_type="payment",
        legal_entity=str(_branch(tenant_a).id),
        date="2026-09-23",
        treasury_kind="cash_box",
        treasury_id=cash_box["id"],
        party=str(employee.id),
        party_role="employee",
        lines=[{"line_type": "on_account", "amount_fc": "200.00"}],
    )
    assert response.status_code == 201, response.data
    voucher = _post(client_a, response.data["id"])
    assert voucher.status_code == 200, voucher.data
    voucher = voucher.data

    entry = JournalEntry.objects.get(id=voucher["journal_entry_id"])
    employees_parent = Account.objects.get(tenant=tenant_a, system_key="EMPLOYEES")
    employee_account = employees_parent.children.first()
    line = entry.lines.get(account=employee_account)
    assert line.debit == Decimal("200.00")


@pytest.mark.django_db
def test_voucher_numbering_assigned_at_post_not_draft(tenant_a, client_a):
    customer = PartyFactory(tenant=tenant_a)
    bank = _make_bank(client_a, tenant_a)
    invoice = _make_invoice(client_a, tenant_a, customer, tax_code_code="Z", amount="1000.00")

    response = _create_voucher(
        client_a,
        voucher_type="receipt",
        legal_entity=str(_branch(tenant_a).id),
        date="2026-09-23",
        treasury_kind="bank",
        treasury_id=bank["id"],
        party=str(customer.id),
        party_role="customer",
        lines=[{"line_type": "invoice", "invoice": invoice["id"], "amount_fc": "1000.00", "allocated_invoice_fc": "1000.00"}],
    )
    assert response.data["number"] == ""
    posted = _post(client_a, response.data["id"]).data
    assert posted["number"].startswith("RV")


@pytest.mark.django_db
def test_tenant_isolation_on_invoice_line(tenant_a, client_a, tenant_b, client_b):
    customer_b = PartyFactory(tenant=tenant_b)
    invoice_b = _make_invoice(client_b, tenant_b, customer_b, tax_code_code="Z", amount="1000.00")
    bank_a = _make_bank(client_a, tenant_a)
    customer_a = PartyFactory(tenant=tenant_a)

    response = _create_voucher(
        client_a,
        voucher_type="receipt",
        legal_entity=str(_branch(tenant_a).id),
        date="2026-09-23",
        treasury_kind="bank",
        treasury_id=bank_a["id"],
        party=str(customer_a.id),
        party_role="customer",
        lines=[{"line_type": "invoice", "invoice": invoice_b["id"], "amount_fc": "1000.00", "allocated_invoice_fc": "1000.00"}],
    )
    assert response.status_code == 400, response.data
