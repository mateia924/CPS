"""Sprint 8.2 (docs/prompts/sprint-8.md block 8.2, D7): payment vouchers
allocated to supplier bills with the realized FX difference, supplier
advances applied from the bill, payables aging, the weekly payables report,
the supplier statement's open bills, and «دفع نقدي الآن».

The spec's fixed numbers: a 1,000 USD bill at 3.75 settled at 3.80 -> a 50
loss on the differences account; a partial allocation leaves the remainder
in its correct aging bucket; a 2,000 advance against a 3,000 bill leaves
1,000 outstanding. And the allocation table's new rule: exactly one target.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from apps.accounting.models import JournalEntry
from apps.purchasing.models import AdvanceApplication, SupplierBill
from apps.treasury.models import ExchangeRate
from apps.vouchers.models import VoucherAllocation

from .factories import PartyFactory, UserFactory
from .test_sprint8_block1 import _branch, _create, _expense_account, _line, _supplier, _tax
from .test_sprint8_block1 import _post as _post_bill
from .test_vouchers import _make_invoice


@pytest.fixture
def purchasing(tenant_a):
    tenant_a.features.purchasing = True
    tenant_a.features.save(update_fields=["purchasing"])
    return tenant_a


def _bank(client, tenant, currency="SAR"):
    response = client.post(
        "/api/banks/", {"legal_entity": str(_branch(tenant).id), "name": f"Bank {currency}", "currency": currency},
        format="json",
    )
    assert response.status_code == 201, response.data
    return response.data


def _bill(client, tenant, supplier, amount, bill_number, currency=None, rate=None, due_date=None, post=True):
    header = {}
    if currency:
        header.update({"currency": currency, "exchange_rate": rate})
    if due_date:
        header["due_date"] = due_date
    created = _create(
        client, tenant, supplier,
        [_line("expense", amount, _tax(tenant, "Z"), account=str(_expense_account(tenant).id))],
        bill_number=bill_number, **header,
    )
    assert created.status_code == 201, created.data
    return _post_bill(client, created.data["id"]) if post else created.data


def _payment(client, tenant, bank, supplier, lines, rate=None, expect=201):
    body = {
        "voucher_type": "payment", "legal_entity": str(_branch(tenant).id), "date": "2026-03-20",
        "treasury_kind": "bank", "treasury_id": bank["id"], "party": str(supplier.id), "party_role": "supplier",
        "lines": lines,
    }
    if rate:
        body["exchange_rate"] = rate
    response = client.post("/api/vouchers/", body, format="json")
    assert response.status_code == expect, response.data
    return response


def _post_voucher(client, voucher_id):
    posted = client.post(f"/api/vouchers/{voucher_id}/post/")
    assert posted.status_code == 200, posted.data
    return posted.data


def _entry(voucher_id):
    from apps.vouchers.models import Voucher

    return Voucher.objects.get(id=voucher_id).journal_entry


def _by_key(entry):
    out = {}
    for line in entry.lines.select_related("account"):
        key = "supplier" if line.account.party_id else (line.account.system_key or line.account.code)
        d, c = out.get(key, (Decimal("0"), Decimal("0")))
        out[key] = (d + line.debit, c + line.credit)
    assert sum(d for d, _ in out.values()) == sum(c for _, c in out.values())
    return out


# --- the allocation table: exactly one target ---------------------------------


@pytest.mark.django_db
def test_an_allocation_must_target_exactly_one_document(purchasing, client_a):
    """voucherallocation_exactly_one_target (vouchers 0007/0008): the database
    refuses an allocation with neither target and one with both."""
    customer = PartyFactory(tenant=purchasing)
    invoice = _make_invoice(client_a, purchasing, customer)
    made = client_a.post(
        "/api/banks/", {"legal_entity": invoice["legal_entity"], "name": "Bank inv", "currency": "SAR"}, format="json"
    )
    assert made.status_code == 201, made.data
    bank = made.data
    receipt = client_a.post("/api/vouchers/", {
        "voucher_type": "receipt", "legal_entity": invoice["legal_entity"], "date": "2026-03-20",
        "treasury_kind": "bank", "treasury_id": bank["id"], "party": str(customer.id), "party_role": "customer",
        "lines": [{"line_type": "invoice", "invoice": invoice["id"], "amount_fc": invoice["total"]}],
    }, format="json")
    assert receipt.status_code == 201, receipt.data
    _post_voucher(client_a, receipt.data["id"])
    allocation = VoucherAllocation.objects.get(invoice_id=invoice["id"])
    bill = SupplierBill.objects.get(id=_bill(client_a, purchasing, _supplier(purchasing), "100.00", "X-1")["id"])

    with pytest.raises(IntegrityError, match="voucherallocation_exactly_one_target"), transaction.atomic():
        VoucherAllocation.objects.filter(pk=allocation.pk).update(invoice=None)
    with pytest.raises(IntegrityError, match="voucherallocation_exactly_one_target"), transaction.atomic():
        VoucherAllocation.objects.filter(pk=allocation.pk).update(supplier_bill=bill)


# --- the spec's fixed numbers -----------------------------------------------


@pytest.mark.django_db
def test_usd_bill_at_3_75_settled_at_3_80_books_a_50_loss(purchasing, client_a):
    supplier = _supplier(purchasing, "US Vendor")
    bill = _bill(client_a, purchasing, supplier, "1000.00", "US-1", currency="USD", rate="3.75")
    assert bill["base_total"] == "3750.00"
    bank = _bank(client_a, purchasing, "USD")
    voucher = _payment(client_a, purchasing, bank, supplier, [
        {"line_type": "bill", "supplier_bill": bill["id"], "amount_fc": "1000.00", "allocated_invoice_fc": "1000.00"}
    ], rate="3.80")
    _post_voucher(client_a, voucher.data["id"])

    lines = _by_key(_entry(voucher.data["id"]))
    assert lines.pop("supplier") == (Decimal("3750.00"), Decimal("0"))
    assert lines.pop("FX_REALIZED") == (Decimal("50.00"), Decimal("0"))  # a loss: more base paid than the bill booked
    assert list(lines.values()) == [(Decimal("0"), Decimal("3800.00"))]  # the USD bank, 1,000 x 3.80
    allocation = VoucherAllocation.objects.get(supplier_bill_id=bill["id"])
    assert (allocation.base_at_invoice_rate, allocation.base_settled, allocation.fx_difference_base) == (
        Decimal("3750.00"), Decimal("3800.00"), Decimal("50.00"),
    )
    assert client_a.get(f"/api/purchasing/bills/{bill['id']}/").data["balance_fc"] == "0.00"


@pytest.mark.django_db
def test_a_partial_allocation_leaves_the_remainder_in_its_aging_bucket(purchasing, client_a):
    supplier = _supplier(purchasing, "مورد جزئي")
    bill = _bill(client_a, purchasing, supplier, "3000.00", "P-1", due_date="2026-04-01")
    bank = _bank(client_a, purchasing)
    voucher = _payment(client_a, purchasing, bank, supplier, [
        {"line_type": "bill", "supplier_bill": bill["id"], "amount_fc": "1000.00"}
    ])
    _post_voucher(client_a, voucher.data["id"])
    assert client_a.get(f"/api/purchasing/bills/{bill['id']}/").data["balance_fc"] == "2000.00"

    # 45 days past due on 2026-05-16 -> "31-60".
    aging = client_a.get("/api/reports/aging/?side=payable&as_of=2026-05-16")
    assert aging.status_code == 200, aging.data
    rows = [r for r in aging.data["rows"] if r["reference"] == bill["number"]]
    assert [(r["amount_base"], r["bucket"], r["source"]) for r in rows] == [("2000.00", "31-60", "supplier_bill")]
    assert aging.data["total"] == "2000.00"


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["advance", "on_account"])
def test_a_2000_advance_against_a_3000_bill_leaves_1000_outstanding(purchasing, client_a, kind):
    supplier = _supplier(purchasing, "مورد بدفعة مقدمة")
    bank = _bank(client_a, purchasing)
    advance = _payment(client_a, purchasing, bank, supplier, [{"line_type": kind, "amount_fc": "2000.00"}])
    _post_voucher(client_a, advance.data["id"])
    if kind == "advance":
        assert _by_key(_entry(advance.data["id"]))["SUPPLIER_ADVANCES"] == (Decimal("2000.00"), Decimal("0"))
    bill = _bill(client_a, purchasing, supplier, "3000.00", f"ADV-{kind}")

    offered = client_a.get(f"/api/purchasing/bills/{bill['id']}/open-advances/").data
    assert [(o["kind"], o["remaining_fc"]) for o in offered] == [(kind, "2000.00")]
    applied = client_a.post(
        f"/api/purchasing/bills/{bill['id']}/apply-advance/", {"source_line": offered[0]["line_id"], "amount": "2000.00"},
        format="json",
    )
    assert applied.status_code == 200, applied.data
    assert applied.data["balance_fc"] == "1000.00"
    application = AdvanceApplication.objects.get(supplier_bill_id=bill["id"])
    if kind == "advance":
        assert _by_key(application.journal_entry) == {
            "supplier": (Decimal("2000.00"), Decimal("0")),
            "SUPPLIER_ADVANCES": (Decimal("0"), Decimal("2000.00")),
        }
        assert application.journal_entry.produced_by == JournalEntry.ProducedBy.ADVANCE_APPLICATION
    else:
        assert application.journal_entry is None  # same rate: the debit is already on the supplier's account
    assert client_a.get(f"/api/purchasing/bills/{bill['id']}/open-advances/").data == []


# --- pay now, statement, weekly report ---------------------------------------


@pytest.mark.django_db
def test_pay_now_creates_a_payment_voucher_fully_allocated_to_the_bill(purchasing, client_a):
    supplier = _supplier(purchasing, "مورد نقدي")
    bill = _bill(client_a, purchasing, supplier, "1150.00", "N-1")
    bank = _bank(client_a, purchasing)
    paid = client_a.post(
        f"/api/purchasing/bills/{bill['id']}/pay-now/", {"treasury_kind": "bank", "treasury_id": bank["id"]}, format="json"
    )
    assert paid.status_code == 201, paid.data
    assert paid.data["voucher_status"] == "posted" and paid.data["voucher_number"]
    allocation = VoucherAllocation.objects.get(supplier_bill_id=bill["id"])
    assert allocation.allocated_invoice_fc == Decimal("1150.00")
    detail = client_a.get(f"/api/purchasing/bills/{bill['id']}/").data
    assert (detail["paid_fc"], detail["balance_fc"]) == ("1150.00", "0.00")
    assert detail["payments"][0]["voucher_number"] == paid.data["voucher_number"]


@pytest.mark.django_db
def test_supplier_statement_lists_open_bills_and_names_each_lines_document(purchasing, client_a):
    supplier = _supplier(purchasing, "مورد الكشف")
    open_bill = _bill(client_a, purchasing, supplier, "500.00", "S-1")
    paid_bill = _bill(client_a, purchasing, supplier, "200.00", "S-2")
    bank = _bank(client_a, purchasing)
    client_a.post(f"/api/purchasing/bills/{paid_bill['id']}/pay-now/", {"treasury_kind": "bank", "treasury_id": bank["id"]}, format="json")

    statement = client_a.get(f"/api/parties/{supplier.id}/statement/?role=supplier")
    assert statement.status_code == 200, statement.data
    assert [b["number"] for b in statement.data["open_bills"]] == [open_bill["number"]]
    kinds = {(line["content_type"], line["produced_by"]) for line in statement.data["lines"]}
    assert ("supplierbill", "supplier_bill") in kinds and ("voucher", "voucher_payment") in kinds


@pytest.mark.django_db
def test_an_applied_advance_links_its_bill_on_the_supplier_statement(purchasing, client_a):
    supplier = _supplier(purchasing, "مورد كشف المقدم")
    bank = _bank(client_a, purchasing)
    advance = _payment(client_a, purchasing, bank, supplier, [{"line_type": "advance", "amount_fc": "300.00"}])
    _post_voucher(client_a, advance.data["id"])
    bill = _bill(client_a, purchasing, supplier, "500.00", "SA-1")
    line = client_a.get(f"/api/purchasing/bills/{bill['id']}/open-advances/").data[0]["line_id"]
    client_a.post(f"/api/purchasing/bills/{bill['id']}/apply-advance/", {"source_line": line, "amount": "300.00"}, format="json")

    statement = client_a.get(f"/api/parties/{supplier.id}/statement/?role=supplier").data
    applied = [row for row in statement["lines"] if row["produced_by"] == "advance_application"]
    assert [(row["content_type"], str(row["object_id"])) for row in applied] == [("supplierbill", bill["id"])]


@pytest.mark.django_db
def test_payables_by_week_puts_each_bill_in_its_week(purchasing, client_a):
    supplier = _supplier(purchasing, "مورد أسبوعي")
    overdue = _bill(client_a, purchasing, supplier, "100.00", "W-0", due_date="2026-03-12")
    this_week = _bill(client_a, purchasing, supplier, "200.00", "W-1", due_date="2026-03-19")
    later = _bill(client_a, purchasing, supplier, "300.00", "W-9", due_date="2026-12-31")
    report = client_a.get("/api/purchasing/payables-by-week/?as_of=2026-03-17")  # a Tuesday
    assert report.status_code == 200, report.data
    where = {b["number"]: bucket["key"] for bucket in report.data["buckets"] for b in bucket["bills"]}
    assert where == {overdue["number"]: "overdue", this_week["number"]: "week_1", later["number"]: "later"}
    assert report.data["total"] == "600.00"


# --- guards --------------------------------------------------------------------


@pytest.mark.django_db
def test_a_bill_cannot_be_over_allocated_even_by_two_drafts(purchasing, client_a):
    supplier = _supplier(purchasing, "مورد مزدوج")
    bill = _bill(client_a, purchasing, supplier, "1000.00", "D-1")
    bank = _bank(client_a, purchasing)
    over = _payment(client_a, purchasing, bank, supplier, [
        {"line_type": "bill", "supplier_bill": bill["id"], "amount_fc": "1000.01"}
    ], expect=400)
    assert "remaining balance" in str(over.data)
    first = _payment(client_a, purchasing, bank, supplier, [{"line_type": "bill", "supplier_bill": bill["id"], "amount_fc": "1000.00"}])
    second = _payment(client_a, purchasing, bank, supplier, [{"line_type": "bill", "supplier_bill": bill["id"], "amount_fc": "1000.00"}])
    _post_voucher(client_a, first.data["id"])
    refused = client_a.post(f"/api/vouchers/{second.data['id']}/post/")
    assert refused.status_code == 400
    assert "أكبر من المتبقي عليها الآن" in str(refused.data)
    assert VoucherAllocation.objects.filter(supplier_bill_id=bill["id"]).count() == 1


@pytest.mark.django_db
def test_a_bill_line_belongs_on_a_payment_to_that_bills_supplier(purchasing, client_a):
    supplier, other = _supplier(purchasing, "المورد"), _supplier(purchasing, "مورد آخر")
    bill = _bill(client_a, purchasing, supplier, "100.00", "O-1")
    bank = _bank(client_a, purchasing)
    wrong_party = _payment(client_a, purchasing, bank, other, [{"line_type": "bill", "supplier_bill": bill["id"], "amount_fc": "100.00"}], expect=400)
    assert "does not belong" in str(wrong_party.data)
    draft = _bill(client_a, purchasing, supplier, "100.00", "O-2", post=False)
    unposted = _payment(client_a, purchasing, bank, supplier, [{"line_type": "bill", "supplier_bill": draft["id"], "amount_fc": "100.00"}], expect=400)
    assert "posted supplier bill" in str(unposted.data)


@pytest.mark.django_db
def test_a_bill_with_payments_cannot_be_reversed_and_a_reversed_voucher_reopens_it(purchasing, client_a):
    supplier = _supplier(purchasing, "مورد العكس")
    bill = _bill(client_a, purchasing, supplier, "400.00", "R-1")
    bank = _bank(client_a, purchasing)
    voucher = _payment(client_a, purchasing, bank, supplier, [{"line_type": "bill", "supplier_bill": bill["id"], "amount_fc": "400.00"}])
    _post_voucher(client_a, voucher.data["id"])
    refused = client_a.post(f"/api/purchasing/bills/{bill['id']}/reverse/", {"reason": "خطأ"}, format="json")
    assert refused.status_code == 400 and "عليها سداد" in refused.data["detail"]

    reversed_ = client_a.post(f"/api/vouchers/{voucher.data['id']}/reverse/", {"reason": "سند خاطئ"}, format="json")
    assert reversed_.status_code == 200, reversed_.data
    assert client_a.get(f"/api/purchasing/bills/{bill['id']}/").data["balance_fc"] == "400.00"
    assert client_a.post(f"/api/purchasing/bills/{bill['id']}/reverse/", {"reason": "خطأ"}, format="json").status_code == 200


@pytest.mark.django_db
def test_an_applied_advance_cannot_be_reversed_until_withdrawn(purchasing, client_a):
    supplier = _supplier(purchasing, "مورد مقدم")
    bank = _bank(client_a, purchasing)
    advance = _payment(client_a, purchasing, bank, supplier, [{"line_type": "advance", "amount_fc": "500.00"}])
    _post_voucher(client_a, advance.data["id"])
    bill = _bill(client_a, purchasing, supplier, "800.00", "A-1")
    line = client_a.get(f"/api/purchasing/bills/{bill['id']}/open-advances/").data[0]["line_id"]
    over = client_a.post(f"/api/purchasing/bills/{bill['id']}/apply-advance/", {"source_line": line, "amount": "500.01"}, format="json")
    assert over.status_code == 400 and "المتبقي من الدفعة المقدمة" in str(over.data)
    assert client_a.post(f"/api/purchasing/bills/{bill['id']}/apply-advance/", {"source_line": line, "amount": "500.00"}, format="json").status_code == 200

    refused = client_a.post(f"/api/vouchers/{advance.data['id']}/reverse/", {"reason": "خطأ"}, format="json")
    assert refused.status_code == 400 and "مخصَّصة لفاتورة المورد" in str(refused.data)
    application = AdvanceApplication.objects.get(supplier_bill_id=bill["id"])
    withdrawn = client_a.post(
        f"/api/purchasing/bills/{bill['id']}/withdraw-advance/", {"application": str(application.id), "reason": "خطأ"}, format="json"
    )
    assert withdrawn.status_code == 200 and withdrawn.data["balance_fc"] == "800.00"
    assert client_a.post(f"/api/vouchers/{advance.data['id']}/reverse/", {"reason": "خطأ"}, format="json").status_code == 200


@pytest.mark.django_db
def test_pay_now_needs_the_voucher_posting_permission_and_the_bills_currency(purchasing, client_a):
    from apps.access.models import Permission, Role

    supplier = _supplier(purchasing, "مورد صلاحيات")
    bill = _bill(client_a, purchasing, supplier, "100.00", "PN-1")
    usd_bank = _bank(client_a, purchasing, "USD")
    # A USD->SAR rate exists, so only the currency guard stands between a
    # SAR bill and a USD voucher allocating its amount 1:1.
    ExchangeRate.objects.create(tenant=purchasing, from_currency="USD", to_currency="SAR", date="2026-01-01", rate="3.75")
    wrong = client_a.post(f"/api/purchasing/bills/{bill['id']}/pay-now/", {"treasury_kind": "bank", "treasury_id": usd_bank["id"]}, format="json")
    assert wrong.status_code == 400 and "غير عملة الفاتورة" in str(wrong.data)
    assert not VoucherAllocation.objects.filter(supplier_bill_id=bill["id"]).exists()

    role = Role.objects.create(tenant=purchasing, name="Buyer who posts")
    role.permissions.set(Permission.objects.filter(code__in=["purchasing.view", "purchasing.post"]))
    buyer = UserFactory(tenant=purchasing)
    buyer.roles.add(role)
    from apps.access.models import UserEntityAccess

    UserEntityAccess.objects.create(user=buyer, legal_entity=_branch(purchasing))
    client = APIClient()
    client.force_authenticate(buyer)
    sar_bank = _bank(client_a, purchasing)
    refused = client.post(f"/api/purchasing/bills/{bill['id']}/pay-now/", {"treasury_kind": "bank", "treasury_id": sar_bank["id"]}, format="json")
    assert refused.status_code == 403 and "ترحيل السندات" in refused.data["detail"]
    assert not VoucherAllocation.objects.filter(supplier_bill_id=bill["id"]).exists()


@pytest.mark.django_db
def test_aging_side_must_be_receivable_or_payable(purchasing, client_a):
    assert client_a.get("/api/reports/aging/?side=sideways").status_code == 400
    assert client_a.get("/api/reports/aging/").data["side"] == "receivable"


def test_the_spec_dates_used_here_are_what_they_claim():
    assert date(2026, 3, 17).weekday() == 1  # Tuesday: week_1 is 16-22 March
    assert (date(2026, 5, 16) - date(2026, 4, 1)).days == 45
