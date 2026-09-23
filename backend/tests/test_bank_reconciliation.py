"""Sprint 5.5 (block 5.5.2, v2 decisions 1-4/10): the matching engine —
automatic (single-candidate) and manual (including grouped, signed)
matching, unmatch/ignore, "voucher from statement line", and the
reversal-of-a-matched-line warning — against the real HTTP API and real
Postgres, matching this project's testing philosophy throughout.
"""

import datetime
import json

import pytest

from apps.accounting.models import Account, TaxCode
from apps.organization.models import LegalEntity

from .factories import BankFactory


def _branch(tenant):
    return LegalEntity.objects.get(tenant=tenant, entity_type=LegalEntity.Type.BRANCH)


def _bank(tenant, currency="SAR"):
    from apps.accounting.services import get_or_create_treasury_account

    bank = BankFactory(tenant=tenant, currency=currency, legal_entity=_branch(tenant))
    get_or_create_treasury_account(bank, "BANKS")
    bank.refresh_from_db()
    return bank


def _create_voucher(client, **payload):
    return client.post("/api/vouchers/", payload, format="json")


def _post(client, voucher_id):
    return client.post(f"/api/vouchers/{voucher_id}/post/")


def _revenue_account(tenant):
    return Account.objects.filter(tenant=tenant, code="4100").first()


def _expense_account(tenant):
    return Account.objects.filter(tenant=tenant, code="5100").first()


def _deposit(client, tenant, bank, amount, date="2026-01-05"):
    """A RECEIPT voucher posted to `bank` — the bank-side journal line
    ends up debit_fc=amount (a deposit)."""
    tax_code = TaxCode.objects.get(tenant=tenant, code="Z")
    response = _create_voucher(
        client, voucher_type="receipt", legal_entity=str(_branch(tenant).id), date=date,
        treasury_kind="bank", treasury_id=str(bank.id), payee_name="Depositor",
        lines=[{"line_type": "account", "account": str(_revenue_account(tenant).id), "tax_code": str(tax_code.id), "amount_fc": amount}],
    )
    assert response.status_code == 201, response.data
    posted = _post(client, response.data["id"])
    assert posted.status_code == 200, posted.data
    return posted.data


def _withdrawal(client, tenant, bank, amount, date="2026-01-05"):
    """A PAYMENT voucher posted to `bank` — the bank-side journal line
    ends up credit_fc=amount (a withdrawal/fee)."""
    tax_code = TaxCode.objects.get(tenant=tenant, code="Z")
    response = _create_voucher(
        client, voucher_type="payment", legal_entity=str(_branch(tenant).id), date=date,
        treasury_kind="bank", treasury_id=str(bank.id), payee_name="Bank fee",
        lines=[{"line_type": "account", "account": str(_expense_account(tenant).id), "tax_code": str(tax_code.id), "amount_fc": amount}],
    )
    assert response.status_code == 201, response.data
    posted = _post(client, response.data["id"])
    assert posted.status_code == 200, posted.data
    return posted.data


def _import_statement(client, bank, lines, period_start="2026-01-01", period_end="2026-01-31",
                       opening_balance="0.00", closing_balance="0.00"):
    content = "\n".join(
        ["Date,Amount,Description"] + [f"{d},{a},{desc}" for d, a, desc in lines]
    )
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
# automatic matching
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_single_candidate_auto_matched_on_import(tenant_a, client_a):
    bank = _bank(tenant_a)
    _deposit(client_a, tenant_a, bank, "500.00", date="2026-01-05")

    response = _import_statement(client_a, bank, [("2026-01-05", "500.00", "Deposit")])
    assert response.status_code == 201, response.data
    assert response.data["auto_matched"] == 1
    assert response.data["unmatched"] == 0
    assert response.data["lines"][0]["status"] == "matched"
    assert response.data["lines"][0]["matched_by"] == "auto"


@pytest.mark.django_db
def test_two_candidates_same_amount_stays_unmatched_with_ordered_list(tenant_a, client_a):
    bank = _bank(tenant_a)
    _deposit(client_a, tenant_a, bank, "300.00", date="2026-01-05")
    _deposit(client_a, tenant_a, bank, "300.00", date="2026-01-06")

    response = _import_statement(client_a, bank, [("2026-01-05", "300.00", "Deposit")])
    assert response.status_code == 201, response.data
    assert response.data["auto_matched"] == 0
    line_id = response.data["lines"][0]["id"]
    assert response.data["lines"][0]["status"] == "unmatched"

    candidates = client_a.get(f"/api/statement-lines/{line_id}/candidates/")
    assert candidates.status_code == 200, candidates.data
    assert len(candidates.data) == 2
    # closer date first
    assert candidates.data[0]["date"] == datetime.date(2026, 1, 5)


@pytest.mark.django_db
def test_candidate_outside_date_window_not_matched(tenant_a, client_a):
    bank = _bank(tenant_a)
    _deposit(client_a, tenant_a, bank, "400.00", date="2026-01-01")

    response = _import_statement(client_a, bank, [("2026-01-10", "400.00", "Deposit")])
    assert response.status_code == 201, response.data
    assert response.data["auto_matched"] == 0
    line_id = response.data["lines"][0]["id"]
    candidates = client_a.get(f"/api/statement-lines/{line_id}/candidates/")
    assert candidates.data == []


# ---------------------------------------------------------------------
# manual matching (including grouped/signed)
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_grouped_manual_match_receipt_plus_fee(tenant_a, client_a):
    bank = _bank(tenant_a)
    receipt = _deposit(client_a, tenant_a, bank, "1000.00", date="2026-01-05")
    fee = _withdrawal(client_a, tenant_a, bank, "15.00", date="2026-01-05")

    response = _import_statement(client_a, bank, [("2026-01-05", "985.00", "Net deposit")])
    assert response.status_code == 201, response.data
    assert response.data["auto_matched"] == 0
    line_id = response.data["lines"][0]["id"]

    receipt_entry_id = receipt["journal_entry_id"]
    fee_entry_id = fee["journal_entry_id"]
    from apps.accounting.models import JournalLine

    bank_account_id = str(bank.gl_account_id)
    receipt_line = JournalLine.objects.get(entry_id=receipt_entry_id, account_id=bank_account_id)
    fee_line = JournalLine.objects.get(entry_id=fee_entry_id, account_id=bank_account_id)

    match = client_a.post(
        f"/api/statement-lines/{line_id}/match/",
        {"journal_line_ids": [str(receipt_line.id), str(fee_line.id)]}, format="json",
    )
    assert match.status_code == 200, match.data
    assert match.data["status"] == "matched"
    assert match.data["matched_by"] == "manual"

    receipt_line.refresh_from_db()
    fee_line.refresh_from_db()
    assert str(receipt_line.bank_statement_line_id) == line_id
    assert str(fee_line.bank_statement_line_id) == line_id


@pytest.mark.django_db
def test_manual_match_sum_mismatch_rejected(tenant_a, client_a):
    bank = _bank(tenant_a)
    receipt = _deposit(client_a, tenant_a, bank, "1000.00", date="2026-01-05")
    response = _import_statement(client_a, bank, [("2026-01-05", "985.00", "Net deposit")])
    line_id = response.data["lines"][0]["id"]

    from apps.accounting.models import JournalLine

    receipt_line = JournalLine.objects.get(entry_id=receipt["journal_entry_id"], account_id=bank.gl_account_id)
    match = client_a.post(
        f"/api/statement-lines/{line_id}/match/", {"journal_line_ids": [str(receipt_line.id)]}, format="json",
    )
    assert match.status_code == 400, match.data


@pytest.mark.django_db
def test_already_matched_journal_line_rejected_from_second_match(tenant_a, client_a):
    bank = _bank(tenant_a)
    _deposit(client_a, tenant_a, bank, "200.00", date="2026-01-05")
    response = _import_statement(
        client_a, bank, [("2026-01-05", "200.00", "First"), ("2026-01-06", "200.00", "Second")],
        period_start="2026-01-01", period_end="2026-01-31",
    )
    lines = response.data["lines"]
    assert response.data["auto_matched"] == 1  # only one had a unique candidate
    matched_line = next(line for line in lines if line["status"] == "matched")
    unmatched_line = next(line for line in lines if line["status"] == "unmatched")

    from apps.accounting.models import JournalLine

    already_matched_journal_line = JournalLine.objects.get(bank_statement_line_id=matched_line["id"])
    second_attempt = client_a.post(
        f"/api/statement-lines/{unmatched_line['id']}/match/",
        {"journal_line_ids": [str(already_matched_journal_line.id)]}, format="json",
    )
    assert second_attempt.status_code == 400, second_attempt.data


@pytest.mark.django_db
def test_unmatch_reverts_journal_lines(tenant_a, client_a):
    bank = _bank(tenant_a)
    _deposit(client_a, tenant_a, bank, "500.00", date="2026-01-05")
    response = _import_statement(client_a, bank, [("2026-01-05", "500.00", "Deposit")])
    line_id = response.data["lines"][0]["id"]
    assert response.data["auto_matched"] == 1

    unmatch = client_a.post(f"/api/statement-lines/{line_id}/unmatch/")
    assert unmatch.status_code == 200, unmatch.data
    assert unmatch.data["status"] == "unmatched"

    from apps.accounting.models import JournalLine

    assert JournalLine.objects.filter(bank_statement_line_id=line_id).count() == 0


@pytest.mark.django_db
def test_ignore_requires_reason_and_counts_as_settled(tenant_a, client_a):
    bank = _bank(tenant_a)
    response = _import_statement(client_a, bank, [("2026-01-05", "12.34", "Unrelated interest")])
    line_id = response.data["lines"][0]["id"]

    no_reason = client_a.post(f"/api/statement-lines/{line_id}/ignore/", {"reason": ""}, format="json")
    assert no_reason.status_code == 400, no_reason.data

    ignored = client_a.post(f"/api/statement-lines/{line_id}/ignore/", {"reason": "Foreign fee, no local entry"}, format="json")
    assert ignored.status_code == 200, ignored.data
    assert ignored.data["status"] == "ignored"

    statement = client_a.get(f"/api/bank-statements/{response.data['id']}/")
    assert statement.data["reconciled_ratio"] == 1.0


# ---------------------------------------------------------------------
# voucher from statement line
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_voucher_created_from_statement_line_auto_matches_on_post(tenant_a, client_a):
    bank = _bank(tenant_a)
    response = _import_statement(client_a, bank, [("2026-01-05", "250.00", "Unrecorded deposit")])
    line_id = response.data["lines"][0]["id"]
    assert response.data["auto_matched"] == 0

    tax_code = TaxCode.objects.get(tenant=tenant_a, code="Z")
    voucher = _create_voucher(
        client_a, voucher_type="receipt", legal_entity=str(_branch(tenant_a).id), date="2026-01-05",
        treasury_kind="bank", treasury_id=str(bank.id), payee_name="Late deposit", statement_line=line_id,
        lines=[{"line_type": "account", "account": str(_revenue_account(tenant_a).id), "tax_code": str(tax_code.id), "amount_fc": "250.00"}],
    )
    assert voucher.status_code == 201, voucher.data
    posted = _post(client_a, voucher.data["id"])
    assert posted.status_code == 200, posted.data

    line = client_a.get(f"/api/statement-lines/{line_id}/")
    assert line.data["status"] == "matched"
    assert line.data["matched_by"] == "manual"


@pytest.mark.django_db
def test_voucher_from_statement_line_amount_mismatch_warns_but_posts(tenant_a, client_a):
    bank = _bank(tenant_a)
    response = _import_statement(client_a, bank, [("2026-01-05", "250.00", "Unrecorded deposit")])
    line_id = response.data["lines"][0]["id"]

    tax_code = TaxCode.objects.get(tenant=tenant_a, code="Z")
    voucher = _create_voucher(
        client_a, voucher_type="receipt", legal_entity=str(_branch(tenant_a).id), date="2026-01-05",
        treasury_kind="bank", treasury_id=str(bank.id), payee_name="Wrong amount", statement_line=line_id,
        lines=[{"line_type": "account", "account": str(_revenue_account(tenant_a).id), "tax_code": str(tax_code.id), "amount_fc": "99.00"}],
    )
    assert voucher.status_code == 201, voucher.data
    posted = _post(client_a, voucher.data["id"])
    assert posted.status_code == 200, posted.data
    # Sprint 6.0 (block 6.0, item 5): "match"/"statement" msgids are now
    # Arabic-translated (مطابقة/كشف) — LANGUAGE_CODE="ar" is the default.
    assert any("مطابقة" in w or "كشف" in w for w in posted.data["warnings"])

    line = client_a.get(f"/api/statement-lines/{line_id}/")
    assert line.data["status"] == "unmatched"


# ---------------------------------------------------------------------
# reversal of a matched line
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_reversing_matched_voucher_warns_but_keeps_match(tenant_a, client_a):
    bank = _bank(tenant_a)
    receipt = _deposit(client_a, tenant_a, bank, "500.00", date="2026-01-05")
    response = _import_statement(client_a, bank, [("2026-01-05", "500.00", "Deposit")])
    line_id = response.data["lines"][0]["id"]
    assert response.data["auto_matched"] == 1

    reverse = client_a.post(f"/api/vouchers/{receipt['id']}/reverse/", {"reason": "خطأ"}, format="json")
    assert reverse.status_code == 200, reverse.data
    # Sprint 6.0 (block 6.0, item 5): "reconciled"/"match" msgid is now
    # Arabic-translated (مسوّى/المطابقة).
    assert any("مطابقة" in w or "مسوّى" in w for w in reverse.data["warnings"])

    line = client_a.get(f"/api/statement-lines/{line_id}/")
    assert line.data["status"] == "matched"

    from apps.accounting.models import JournalLine

    reversal_lines = JournalLine.objects.filter(
        account_id=bank.gl_account_id, bank_statement_line__isnull=True
    )
    assert reversal_lines.exists()


# ---------------------------------------------------------------------
# multi-currency + acceptance criterion (≥ 90% on a 50-line statement)
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_usd_bank_matches_on_amount_fc_not_base(tenant_a, client_a):
    bank = _bank(tenant_a, currency="USD")
    from apps.treasury.models import ExchangeRate

    ExchangeRate.objects.create(tenant=tenant_a, from_currency="USD", to_currency="SAR", date="2026-01-01", rate="3.75")
    _deposit(client_a, tenant_a, bank, "100.00", date="2026-01-05")

    response = _import_statement(client_a, bank, [("2026-01-05", "100.00", "USD deposit")])
    assert response.status_code == 201, response.data
    assert response.data["auto_matched"] == 1


@pytest.mark.django_db
def test_fifty_line_statement_matches_at_least_90_percent(tenant_a, client_a):
    bank = _bank(tenant_a)
    lines = []
    for i in range(45):
        amount = f"{100 + i}.00"
        date = "2026-01-05"
        _deposit(client_a, tenant_a, bank, amount, date=date)
        lines.append((date, amount, f"Deposit {i}"))
    for i in range(5):
        lines.append(("2026-01-20", f"{9000 + i}.00", f"Unrecorded {i}"))

    response = _import_statement(
        client_a, bank, lines, period_start="2026-01-01", period_end="2026-01-31",
    )
    assert response.status_code == 201, response.data
    ratio = response.data["auto_matched"] / 50
    assert ratio >= 0.9, response.data


# ---------------------------------------------------------------------
# tenant isolation
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_statement_line_actions_are_tenant_isolated(tenant_a, client_a, tenant_b, client_b):
    bank = _bank(tenant_a)
    response = _import_statement(client_a, bank, [("2026-01-05", "10.00", "x")])
    line_id = response.data["lines"][0]["id"]

    for action in ("match", "unmatch", "ignore", "candidates"):
        if action == "candidates":
            resp = client_b.get(f"/api/statement-lines/{line_id}/candidates/")
        elif action == "unmatch":
            resp = client_b.post(f"/api/statement-lines/{line_id}/unmatch/")
        elif action == "ignore":
            resp = client_b.post(f"/api/statement-lines/{line_id}/ignore/", {"reason": "x"}, format="json")
        else:
            resp = client_b.post(f"/api/statement-lines/{line_id}/match/", {"journal_line_ids": []}, format="json")
        assert resp.status_code == 404, (action, resp.data if hasattr(resp, "data") else resp.content)
