"""Sprint 5.4 (docs/prompts/sprint-5.md block 5.4): internal transfers
(SETTLEMENT/INTERNAL_TRANSFER), the custody cycle exercised end to end
through the receipt/payment/transfer engine already built in 5.3, and
the two read-only verification statements (treasury movements, party
statement) built on the shared `ledger_lines()` service. Real Postgres,
real HTTP API throughout.
"""

from decimal import Decimal

import pytest

from apps.accounting.models import Account, JournalEntry
from apps.organization.models import LegalEntity
from apps.treasury.models import ExchangeRate

from .factories import PartyFactory


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


def _make_custody(client, tenant, employee, limit_amount=None):
    payload = {
        "legal_entity": str(_branch(tenant).id), "name": "Custody", "currency": "SAR",
        "employee": str(employee.id),
    }
    if limit_amount is not None:
        payload["limit_amount"] = limit_amount
    response = client.post("/api/custodies/", payload, format="json")
    assert response.status_code == 201, response.data
    return response.data


def _post(client, voucher_id):
    return client.post(f"/api/vouchers/{voucher_id}/post/")


def _fund_cash_box(client, tenant, cash_box, amount="1000.00"):
    from apps.accounting.models import TaxCode

    revenue = Account.objects.filter(tenant=tenant, code="4100").first()
    tax_code = TaxCode.objects.get(tenant=tenant, code="Z")
    response = client.post(
        "/api/vouchers/",
        {
            "voucher_type": "receipt", "legal_entity": str(_branch(tenant).id), "date": "2026-09-23",
            "treasury_kind": "cash_box", "treasury_id": cash_box["id"], "payee_name": "Funding",
            "lines": [{"line_type": "account", "account": str(revenue.id), "tax_code": str(tax_code.id), "amount_fc": amount}],
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    posted = _post(client, response.data["id"])
    assert posted.status_code == 200, posted.data


def _transfer(client, **payload):
    return client.post("/api/vouchers/transfer/", payload, format="json")


@pytest.mark.django_db
def test_internal_transfer_same_currency_balances_with_no_fx_line(tenant_a, client_a):
    cash_box = _make_cash_box(client_a, tenant_a)
    _fund_cash_box(client_a, tenant_a, cash_box, amount="1000.00")
    bank = _make_bank(client_a, tenant_a, currency="SAR")

    response = _transfer(
        client_a,
        legal_entity=str(_branch(tenant_a).id), date="2026-09-23",
        treasury_kind="cash_box", treasury_id=cash_box["id"],
        counter_treasury_kind="bank", counter_treasury_id=bank["id"],
        amount_fc="400.00",
    )
    assert response.status_code == 201, response.data
    voucher = _post(client_a, response.data["id"])
    assert voucher.status_code == 200, voucher.data
    voucher = voucher.data
    assert voucher["status"] == "posted"
    assert voucher["number"].startswith("SV")

    entry = JournalEntry.objects.get(id=voucher["journal_entry_id"])
    lines = list(entry.lines.all())
    assert len(lines) == 2
    debit_total = sum((line.debit for line in lines), Decimal("0"))
    credit_total = sum((line.credit for line in lines), Decimal("0"))
    assert debit_total == credit_total == Decimal("400.00")
    fx_account = Account.objects.filter(tenant=tenant_a, system_key="FX_REALIZED").first()
    assert not entry.lines.filter(account=fx_account).exists()


@pytest.mark.django_db
def test_internal_transfer_cross_currency_no_fx_difference_posted(tenant_a, client_a):
    ExchangeRate.objects.create(tenant=tenant_a, from_currency="USD", to_currency="SAR", date="2026-09-01", rate="3.80")
    cash_box = _make_cash_box(client_a, tenant_a)
    _fund_cash_box(client_a, tenant_a, cash_box, amount="5000.00")
    bank_usd = _make_bank(client_a, tenant_a, currency="USD")

    response = _transfer(
        client_a,
        legal_entity=str(_branch(tenant_a).id), date="2026-09-23",
        treasury_kind="cash_box", treasury_id=cash_box["id"],
        counter_treasury_kind="bank", counter_treasury_id=bank_usd["id"],
        amount_fc="3800.00", counter_amount_fc="1000.00",
    )
    assert response.status_code == 201, response.data
    voucher = _post(client_a, response.data["id"])
    assert voucher.status_code == 200, voucher.data
    voucher = voucher.data

    entry = JournalEntry.objects.get(id=voucher["journal_entry_id"])
    lines = list(entry.lines.all())
    assert len(lines) == 2
    debit_total = sum((line.debit for line in lines), Decimal("0"))
    credit_total = sum((line.credit for line in lines), Decimal("0"))
    assert debit_total == credit_total == Decimal("3800.00")

    bank_gl = Account.objects.get(tenant=tenant_a, id=Account.objects.get(tenant=tenant_a, system_key="BANKS").children.first().id)
    bank_line = entry.lines.get(account=bank_gl)
    assert bank_line.debit_fc == Decimal("1000.00")
    assert bank_line.debit == Decimal("3800.00")

    from apps.treasury.services import treasury_balance

    bank_balance = treasury_balance(tenant_a, "bank", bank_usd["id"])
    assert bank_balance["fc"] == Decimal("1000.00")


@pytest.mark.django_db
def test_internal_transfer_exceeding_custody_limit_rejected(tenant_a, client_a):
    from apps.parties.models import PartyRole

    employee = PartyFactory(tenant=tenant_a)
    PartyRole.objects.create(party=employee, role=PartyRole.Role.EMPLOYEE)
    cash_box = _make_cash_box(client_a, tenant_a)
    _fund_cash_box(client_a, tenant_a, cash_box, amount="5000.00")
    custody = _make_custody(client_a, tenant_a, employee, limit_amount="2000.00")

    response = _transfer(
        client_a,
        legal_entity=str(_branch(tenant_a).id), date="2026-09-23",
        treasury_kind="cash_box", treasury_id=cash_box["id"],
        counter_treasury_kind="custody", counter_treasury_id=custody["id"],
        amount_fc="2500.00",
    )
    assert response.status_code == 201, response.data
    voucher = _post(client_a, response.data["id"])
    assert voucher.status_code == 400, voucher.data


@pytest.mark.django_db
def test_full_custody_cycle_zeroes_out(tenant_a, client_a):
    from apps.accounting.models import TaxCode
    from apps.parties.models import PartyRole

    employee = PartyFactory(tenant=tenant_a)
    PartyRole.objects.create(party=employee, role=PartyRole.Role.EMPLOYEE)
    cash_box = _make_cash_box(client_a, tenant_a)
    _fund_cash_box(client_a, tenant_a, cash_box, amount="5000.00")
    custody = _make_custody(client_a, tenant_a, employee, limit_amount="3000.00")

    # صرف عهدة: cash box -> custody, 2,000
    disburse = _transfer(
        client_a,
        legal_entity=str(_branch(tenant_a).id), date="2026-09-23",
        treasury_kind="cash_box", treasury_id=cash_box["id"],
        counter_treasury_kind="custody", counter_treasury_id=custody["id"],
        amount_fc="2000.00",
    )
    assert disburse.status_code == 201, disburse.data
    posted = _post(client_a, disburse.data["id"])
    assert posted.status_code == 200, posted.data

    from apps.treasury.services import treasury_balance

    assert treasury_balance(tenant_a, "custody", custody["id"])["fc"] == Decimal("2000.00")

    # تسوية العهدة: PAYMENT voucher from the custody, two expense lines
    # on different cost centers, totalling 1,700.
    from apps.organization.models import CostCenter

    cc1 = CostCenter.objects.filter(tenant=tenant_a).first()
    expense = Account.objects.filter(tenant=tenant_a, code="5100").first()
    tax_code = TaxCode.objects.get(tenant=tenant_a, code="Z")

    settle = client_a.post(
        "/api/vouchers/",
        {
            "voucher_type": "payment", "legal_entity": str(_branch(tenant_a).id), "date": "2026-09-23",
            "treasury_kind": "custody", "treasury_id": custody["id"], "payee_name": "Custody settlement",
            "lines": [
                {"line_type": "account", "account": str(expense.id), "tax_code": str(tax_code.id), "amount_fc": "1000.00", "cost_center": str(cc1.id) if cc1 else None},
                {"line_type": "account", "account": str(expense.id), "tax_code": str(tax_code.id), "amount_fc": "700.00"},
            ],
        },
        format="json",
    )
    assert settle.status_code == 201, settle.data
    posted = _post(client_a, settle.data["id"])
    assert posted.status_code == 200, posted.data
    assert treasury_balance(tenant_a, "custody", custody["id"])["fc"] == Decimal("300.00")

    # استرداد عهدة: custody -> cash box, the remaining 300 — zeroes the
    # custody out entirely (disbursed 2,000, settled 1,700).
    refund = _transfer(
        client_a,
        legal_entity=str(_branch(tenant_a).id), date="2026-09-23",
        treasury_kind="custody", treasury_id=custody["id"],
        counter_treasury_kind="cash_box", counter_treasury_id=cash_box["id"],
        amount_fc="300.00",
    )
    assert refund.status_code == 201, refund.data
    posted = _post(client_a, refund.data["id"])
    assert posted.status_code == 200, posted.data

    assert treasury_balance(tenant_a, "custody", custody["id"])["fc"] == Decimal("0.00")


@pytest.mark.django_db
def test_transfer_exceeding_source_cash_box_balance_rejected(tenant_a, client_a):
    cash_box = _make_cash_box(client_a, tenant_a)
    bank = _make_bank(client_a, tenant_a)

    response = _transfer(
        client_a,
        legal_entity=str(_branch(tenant_a).id), date="2026-09-23",
        treasury_kind="cash_box", treasury_id=cash_box["id"],
        counter_treasury_kind="bank", counter_treasury_id=bank["id"],
        amount_fc="500.00",
    )
    assert response.status_code == 201, response.data
    voucher = _post(client_a, response.data["id"])
    assert voucher.status_code == 400, voucher.data


@pytest.mark.django_db
def test_transfer_source_and_destination_cannot_be_the_same_account(tenant_a, client_a):
    cash_box = _make_cash_box(client_a, tenant_a)
    response = _transfer(
        client_a,
        legal_entity=str(_branch(tenant_a).id), date="2026-09-23",
        treasury_kind="cash_box", treasury_id=cash_box["id"],
        counter_treasury_kind="cash_box", counter_treasury_id=cash_box["id"],
        amount_fc="100.00",
    )
    assert response.status_code == 400, response.data


@pytest.mark.django_db
def test_bank_movements_endpoint_matches_trial_balance(tenant_a, client_a):
    cash_box = _make_cash_box(client_a, tenant_a)
    _fund_cash_box(client_a, tenant_a, cash_box, amount="1000.00")
    bank = _make_bank(client_a, tenant_a)
    transfer = _transfer(
        client_a,
        legal_entity=str(_branch(tenant_a).id), date="2026-09-23",
        treasury_kind="cash_box", treasury_id=cash_box["id"],
        counter_treasury_kind="bank", counter_treasury_id=bank["id"],
        amount_fc="600.00",
    )
    _post(client_a, transfer.data["id"])

    response = client_a.get(f"/api/banks/{bank['id']}/movements/")
    assert response.status_code == 200, response.data
    assert response.data["closing_balance"] == Decimal("600.00")
    assert len(response.data["lines"]) == 1
    assert response.data["lines"][0]["debit"] == Decimal("600.00")


@pytest.mark.django_db
def test_party_statement_shows_running_balance_and_open_invoices(tenant_a, client_a):
    from apps.accounting.models import TaxCode
    from apps.sales.models import Product

    customer = PartyFactory(tenant=tenant_a)
    bank = _make_bank(client_a, tenant_a)
    product = Product.objects.create(tenant=tenant_a, sku="SKU-X", name="Item", unit_price="1000.00")
    tax_code = TaxCode.objects.get(tenant=tenant_a, code="Z")
    invoice_response = client_a.post(
        "/api/invoices/",
        {
            "customer": str(customer.id), "legal_entity": str(_branch(tenant_a).id),
            "lines": [{"product": str(product.id), "quantity": "1", "tax_code": str(tax_code.id)}],
        },
        format="json",
    )
    assert invoice_response.status_code == 201, invoice_response.data
    invoice_id = invoice_response.data["id"]
    issue = client_a.post(f"/api/invoices/{invoice_id}/issue/")
    assert issue.status_code == 200, issue.data

    statement_before = client_a.get(f"/api/parties/{customer.id}/statement/?role=customer")
    assert statement_before.status_code == 200, statement_before.data
    assert len(statement_before.data["open_invoices"]) == 1
    assert statement_before.data["closing_balance"] == Decimal("1000.00")

    voucher = client_a.post(
        "/api/vouchers/",
        {
            "voucher_type": "receipt", "legal_entity": str(_branch(tenant_a).id), "date": "2026-09-23",
            "treasury_kind": "bank", "treasury_id": bank["id"], "party": str(customer.id), "party_role": "customer",
            "lines": [{"line_type": "invoice", "invoice": invoice_id, "amount_fc": "1000.00", "allocated_invoice_fc": "1000.00"}],
        },
        format="json",
    )
    assert voucher.status_code == 201, voucher.data
    posted = _post(client_a, voucher.data["id"])
    assert posted.status_code == 200, posted.data

    statement_after = client_a.get(f"/api/parties/{customer.id}/statement/?role=customer")
    assert statement_after.status_code == 200, statement_after.data
    assert statement_after.data["closing_balance"] == Decimal("0.00")
    assert statement_after.data["open_invoices"] == []


@pytest.mark.django_db
def test_transfer_tenant_isolation(tenant_a, client_a):
    # A treasury id that simply doesn't exist in this tenant (standing
    # in for "belongs to another tenant") must never resolve.
    import uuid

    bank_a = _make_bank(client_a, tenant_a)
    response = _transfer(
        client_a,
        legal_entity=str(_branch(tenant_a).id), date="2026-09-23",
        treasury_kind="bank", treasury_id=bank_a["id"],
        counter_treasury_kind="bank", counter_treasury_id=str(uuid.uuid4()),
        amount_fc="100.00",
    )
    assert response.status_code == 400, response.data


@pytest.mark.django_db
def test_internal_transfer_journal_entry_produced_by_is_voucher_settlement(tenant_a, client_a):
    """Sprint 7.2.7 (§8.7, owner instruction 2026-10-07): voucher_
    settlement has zero rows on live — nothing real ever exercises
    this path, so the only coverage possible is an explicit assertion
    here, not a staging walkthrough (staging mirrors live's real
    activity; inventing a settlement voucher there would test
    something live never actually does). A transfer voucher is
    SETTLEMENT/INTERNAL_TRANSFER under the hood (apps.vouchers.
    services.create_internal_transfer_voucher) — this is the one real
    path that produces that value, and the only test in the whole
    suite that checks produced_by against a concrete expected value
    for any of the three voucher sub-types."""
    cash_box = _make_cash_box(client_a, tenant_a)
    _fund_cash_box(client_a, tenant_a, cash_box, amount="1000.00")
    bank = _make_bank(client_a, tenant_a)

    response = _transfer(
        client_a,
        legal_entity=str(_branch(tenant_a).id), date="2026-09-23",
        treasury_kind="cash_box", treasury_id=cash_box["id"],
        counter_treasury_kind="bank", counter_treasury_id=bank["id"],
        amount_fc="200.00",
    )
    assert response.status_code == 201, response.data
    voucher = _post(client_a, response.data["id"])
    assert voucher.status_code == 200, voucher.data
    assert voucher.data["status"] == "posted"

    entry = JournalEntry.objects.get(id=voucher.data["journal_entry_id"])
    assert entry.produced_by == JournalEntry.ProducedBy.VOUCHER_SETTLEMENT
    assert entry.content_type.model == "voucher"
    assert str(entry.object_id) == response.data["id"]
