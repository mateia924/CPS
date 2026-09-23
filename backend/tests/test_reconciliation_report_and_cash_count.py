"""Sprint 5.5 (block 5.5.3, v2 decisions 8-9): the reconciliation
report ("بصيغة المدقق") and cash count with variance voucher — against
the real HTTP API and real Postgres, matching this project's testing
philosophy throughout.
"""

import json
from decimal import Decimal

import pytest

from apps.accounting.models import Account, TaxCode
from apps.organization.models import LegalEntity

from .factories import BankFactory, CashBoxFactory

# Reuse the same voucher-posting helpers as block 5.5.2's own test
# module would define — kept local (small, self-contained) rather than
# importing across test modules.


def _branch(tenant):
    return LegalEntity.objects.get(tenant=tenant, entity_type=LegalEntity.Type.BRANCH)


def _bank(tenant, currency="SAR"):
    from apps.accounting.services import get_or_create_treasury_account

    bank = BankFactory(tenant=tenant, currency=currency, legal_entity=_branch(tenant))
    get_or_create_treasury_account(bank, "BANKS")
    bank.refresh_from_db()
    return bank


def _cash_box(tenant):
    from apps.accounting.services import get_or_create_treasury_account

    box = CashBoxFactory(tenant=tenant, legal_entity=_branch(tenant))
    get_or_create_treasury_account(box, "CASH")
    box.refresh_from_db()
    return box


def _revenue_account(tenant):
    return Account.objects.filter(tenant=tenant, code="4100").first()


def _deposit(client, tenant, bank, amount, date="2026-01-05"):
    tax_code = TaxCode.objects.get(tenant=tenant, code="Z")
    response = client.post(
        "/api/vouchers/",
        {
            "voucher_type": "receipt", "legal_entity": str(_branch(tenant).id), "date": date,
            "treasury_kind": "bank", "treasury_id": str(bank.id), "payee_name": "Depositor",
            "lines": [{"line_type": "account", "account": str(_revenue_account(tenant).id), "tax_code": str(tax_code.id), "amount_fc": amount}],
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    posted = client.post(f"/api/vouchers/{response.data['id']}/post/")
    assert posted.status_code == 200, posted.data
    return posted.data


def _import_statement(client, bank, lines, period_start="2026-01-01", period_end="2026-01-31",
                       opening_balance="0.00", closing_balance="0.00"):
    content = "\n".join(["Date,Amount,Description"] + [f"{d},{a},{desc}" for d, a, desc in lines])
    from django.core.files.uploadedfile import SimpleUploadedFile

    file_obj = SimpleUploadedFile("s.csv", content.encode(), content_type="text/csv")
    return client.post(
        "/api/bank-statements/import/",
        {
            "bank": str(bank.id), "file": file_obj, "format": "csv",
            "period_start": period_start, "period_end": period_end,
            "opening_balance": opening_balance, "closing_balance": closing_balance,
            "column_mapping": json.dumps({"date": "Date", "amount": "Amount", "description": "Description"}),
        },
        format="multipart",
    )


# ---------------------------------------------------------------------
# reconciliation report
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_report_fully_matched_statement_has_zero_difference_and_full_ratio(tenant_a, client_a):
    bank = _bank(tenant_a)
    _deposit(client_a, tenant_a, bank, "500.00", date="2026-01-05")
    imported = _import_statement(
        client_a, bank, [("2026-01-05", "500.00", "Deposit")],
        opening_balance="0.00", closing_balance="500.00",
    )
    assert imported.data["auto_matched"] == 1

    report = client_a.get(f"/api/banks/{bank.id}/reconciliation-report/?as_of=2026-01-31")
    assert report.status_code == 200, report.data
    assert report.data["difference"] == Decimal("0.00")
    assert report.data["reconciled_ratio"] == 1.0
    assert report.data["outstanding_deposits"] == []
    assert report.data["unrecorded_credits"] == []


@pytest.mark.django_db
def test_report_shows_unrecorded_bank_item_and_reflects_it_in_difference(tenant_a, client_a):
    bank = _bank(tenant_a)
    imported = _import_statement(
        client_a, bank, [("2026-01-05", "75.00", "Bank fee not yet booked")],
        opening_balance="0.00", closing_balance="75.00",
    )
    assert imported.data["auto_matched"] == 0

    report = client_a.get(f"/api/banks/{bank.id}/reconciliation-report/?as_of=2026-01-31")
    assert report.status_code == 200, report.data
    assert len(report.data["unrecorded_credits"]) == 1
    # bank_closing (75) + no outstanding book items = bank_adjusted 75
    # book_closing (0) + unrecorded credit (75) = book_adjusted 75
    assert report.data["difference"] == Decimal("0.00")


@pytest.mark.django_db
def test_report_shows_outstanding_book_payment_not_yet_on_bank(tenant_a, client_a):
    bank = _bank(tenant_a)
    _deposit(client_a, tenant_a, bank, "200.00", date="2026-01-05")
    # No statement imported at all yet for this period — everything on
    # the book side is "outstanding" relative to a zero bank closing.
    report = client_a.get(f"/api/banks/{bank.id}/reconciliation-report/?as_of=2026-01-31")
    assert report.status_code == 200, report.data
    assert len(report.data["outstanding_deposits"]) == 1
    assert report.data["bank_closing_balance"] == Decimal("0")
    assert report.data["bank_adjusted_balance"] == Decimal("200.00")
    assert report.data["book_closing_balance"] == Decimal("200.00")
    assert report.data["difference"] == Decimal("0.00")


@pytest.mark.django_db
def test_report_currency_is_bank_currency(tenant_a, client_a):
    bank = _bank(tenant_a, currency="EUR")
    report = client_a.get(f"/api/banks/{bank.id}/reconciliation-report/")
    assert report.status_code == 200, report.data
    assert report.data["currency"] == "EUR"


# ---------------------------------------------------------------------
# cash count
# ---------------------------------------------------------------------


def _create_count(client, cash_box, count_date, counted_amount=None, denominations=None):
    data = {"cash_box": str(cash_box.id), "count_date": count_date}
    if counted_amount is not None:
        data["counted_amount"] = counted_amount
    if denominations is not None:
        data["denominations"] = denominations
    return client.post("/api/cash-counts/", data, format="json")


@pytest.mark.django_db
def test_cash_count_zero_difference_confirms_without_reason(tenant_a, client_a):
    box = _cash_box(tenant_a)
    create = _create_count(client_a, box, "2026-01-10", counted_amount="0.00")
    assert create.status_code == 201, create.data
    assert create.data["difference"] == "0.00"
    assert create.data["number"] == ""

    confirm = client_a.post(f"/api/cash-counts/{create.data['id']}/confirm/", {}, format="json")
    assert confirm.status_code == 200, confirm.data
    assert confirm.data["status"] == "confirmed"
    assert confirm.data["number"].startswith("CC")


@pytest.mark.django_db
def test_cash_count_deficit_requires_reason_then_creates_payment_voucher(tenant_a, client_a):
    box = _cash_box(tenant_a)
    tax_code = TaxCode.objects.get(tenant=tenant_a, code="Z")
    fund = client_a.post(
        "/api/vouchers/",
        {
            "voucher_type": "receipt", "legal_entity": str(_branch(tenant_a).id), "date": "2026-01-05",
            "treasury_kind": "cash_box", "treasury_id": str(box.id), "payee_name": "Funding",
            "lines": [{"line_type": "account", "account": str(_revenue_account(tenant_a).id), "tax_code": str(tax_code.id), "amount_fc": "1000.00"}],
        },
        format="json",
    )
    assert fund.status_code == 201, fund.data
    posted = client_a.post(f"/api/vouchers/{fund.data['id']}/post/")
    assert posted.status_code == 200, posted.data

    create = _create_count(client_a, box, "2026-01-10", counted_amount="950.00")
    assert create.status_code == 201, create.data
    assert create.data["difference"] == "-50.00"

    no_reason = client_a.post(f"/api/cash-counts/{create.data['id']}/confirm/", {}, format="json")
    assert no_reason.status_code == 400, no_reason.data

    confirm = client_a.post(
        f"/api/cash-counts/{create.data['id']}/confirm/",
        {"reason": "نقص غير مبرر", "create_variance_voucher": True}, format="json",
    )
    assert confirm.status_code == 200, confirm.data
    assert confirm.data["status"] == "confirmed"
    assert confirm.data["variance_voucher"] is not None

    from apps.treasury.services import treasury_balance

    balance = treasury_balance(tenant_a, "cash_box", box.id)
    assert balance["base"] == 950


@pytest.mark.django_db
def test_cash_count_surplus_creates_receipt_voucher(tenant_a, client_a):
    box = _cash_box(tenant_a)
    create = _create_count(client_a, box, "2026-01-10", counted_amount="25.00")
    assert create.status_code == 201, create.data
    assert create.data["difference"] == "25.00"

    confirm = client_a.post(
        f"/api/cash-counts/{create.data['id']}/confirm/",
        {"reason": "زيادة غير مبررة", "create_variance_voucher": True}, format="json",
    )
    assert confirm.status_code == 200, confirm.data

    from apps.treasury.services import treasury_balance

    balance = treasury_balance(tenant_a, "cash_box", box.id)
    assert balance["base"] == 25


@pytest.mark.django_db
def test_denominations_mismatch_with_counted_amount_rejected(tenant_a, client_a):
    box = _cash_box(tenant_a)
    response = _create_count(
        client_a, box, "2026-01-10", counted_amount="100.00", denominations={"50": 1}
    )
    assert response.status_code == 400, response.data


@pytest.mark.django_db
def test_denominations_alone_compute_counted_amount(tenant_a, client_a):
    box = _cash_box(tenant_a)
    response = _create_count(client_a, box, "2026-01-10", denominations={"50": 2, "10": 3})
    assert response.status_code == 201, response.data
    assert response.data["counted_amount"] == "130.00"


@pytest.mark.django_db
def test_confirmed_by_same_as_counted_by_is_allowed(tenant_a, client_a):
    # Single-active-user tenant — same exception spirit as approvals'
    # segregation of duties (v2 decision 8's warning, not a block).
    box = _cash_box(tenant_a)
    create = _create_count(client_a, box, "2026-01-10", counted_amount="0.00")
    confirm = client_a.post(f"/api/cash-counts/{create.data['id']}/confirm/", {}, format="json")
    assert confirm.status_code == 200, confirm.data


# ---------------------------------------------------------------------
# tenant isolation
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_cash_counts_and_reports_are_tenant_isolated(tenant_a, client_a, tenant_b, client_b):
    box = _cash_box(tenant_a)
    create = _create_count(client_a, box, "2026-01-10", counted_amount="0.00")
    assert create.status_code == 201, create.data

    cross_get = client_b.get(f"/api/cash-counts/{create.data['id']}/")
    assert cross_get.status_code == 404

    bank = _bank(tenant_a)
    cross_report = client_b.get(f"/api/banks/{bank.id}/reconciliation-report/")
    assert cross_report.status_code == 404
