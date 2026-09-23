"""Sprint 5.5 (block 5.5.1, v2 decision 5): bank statement import —
CSV/Excel (column-mapped) and MT940, duplicate-file and period-overlap
guards, the original file kept as an audit-trail Attachment — against
the real HTTP API and real Postgres/MinIO/ClamAV, matching this
project's testing philosophy throughout.
"""

import io

import openpyxl
import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.attachments.models import Attachment
from apps.treasury.models import Bank, BankStatement

from .factories import BankFactory

MT940_SAMPLE = """:20:STATEMENT001
:25:NL00BANK0123456789
:28C:1/1
:60F:C260101EUR1000,00
:61:260102D150,00NTRFNONREF//
:86:Payment to supplier
:61:260103C500,00NTRFNONREF//
:86:Deposit received
:61:260104C200,00NTRFNONREF//
:86:Another deposit
:62F:C260104EUR1550,00
-"""

MT940_BAD_BALANCE_SAMPLE = MT940_SAMPLE.replace("C260104EUR1550,00", "C260104EUR9999,00")


def _bank(tenant, currency="SAR"):
    return BankFactory(tenant=tenant, currency=currency)


def _csv_file(rows, header):
    content = "\n".join([",".join(header)] + [",".join(row) for row in rows])
    return SimpleUploadedFile("statement.csv", content.encode("utf-8"), content_type="text/csv")


def _xlsx_file(rows, header):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(header)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return SimpleUploadedFile(
        "statement.xlsx", buf.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _mt940_file(content=MT940_SAMPLE, name="statement.sta"):
    return SimpleUploadedFile(name, content.encode("utf-8"), content_type="text/plain")


def _import(client, bank, file_obj, import_format, period_start="2026-01-01", period_end="2026-01-31",
            opening_balance="1000.00", closing_balance="1550.00", currency=None, column_mapping=None):
    data = {
        "bank": str(bank.id), "file": file_obj, "format": import_format,
        "period_start": period_start, "period_end": period_end,
        "opening_balance": opening_balance, "closing_balance": closing_balance,
    }
    if currency:
        data["currency"] = currency
    if column_mapping:
        import json

        data["column_mapping"] = json.dumps(column_mapping)
    return client.post("/api/bank-statements/import/", data, format="multipart")


# ---------------------------------------------------------------------
# CSV / Excel
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_csv_with_signed_amount_column(tenant_a, client_a):
    bank = _bank(tenant_a)
    file_obj = _csv_file(
        [["2026-01-05", "-150.00", "Payment to supplier", "REF1"],
         ["2026-01-06", "500.00", "Deposit received", "REF2"]],
        header=["Date", "Amount", "Description", "Reference"],
    )
    response = _import(
        client_a, bank, file_obj, "csv",
        column_mapping={"date": "Date", "amount": "Amount", "description": "Description", "reference": "Reference"},
    )
    assert response.status_code == 201, response.data
    assert response.data["line_count"] == 2
    lines = {line["amount"]: line for line in response.data["lines"]}
    assert "-150.00" in lines
    assert "500.00" in lines


@pytest.mark.django_db
def test_csv_with_debit_credit_columns_same_result(tenant_a, client_a):
    bank = _bank(tenant_a)
    file_obj = _csv_file(
        [["2026-01-05", "150.00", "", "Payment"],
         ["2026-01-06", "", "500.00", "Deposit"]],
        header=["Date", "Debit", "Credit", "Description"],
    )
    response = _import(
        client_a, bank, file_obj, "csv",
        column_mapping={"date": "Date", "debit": "Debit", "credit": "Credit", "description": "Description"},
    )
    assert response.status_code == 201, response.data
    amounts = sorted(line["amount"] for line in response.data["lines"])
    assert amounts == ["-150.00", "500.00"]


@pytest.mark.django_db
def test_xlsx_same_column_mapping_works(tenant_a, client_a):
    bank = _bank(tenant_a)
    file_obj = _xlsx_file(
        [["2026-01-05", -150.00, "Payment"], ["2026-01-06", 500.00, "Deposit"]],
        header=["Date", "Amount", "Description"],
    )
    response = _import(
        client_a, bank, file_obj, "xlsx",
        column_mapping={"date": "Date", "amount": "Amount", "description": "Description"},
    )
    assert response.status_code == 201, response.data
    assert response.data["line_count"] == 2
    # The successful mapping is remembered on the bank for next time.
    bank.refresh_from_db()
    assert bank.import_column_mapping == {"date": "Date", "amount": "Amount", "description": "Description"}


@pytest.mark.django_db
def test_bad_date_row_rejects_whole_batch(tenant_a, client_a):
    bank = _bank(tenant_a)
    file_obj = _csv_file(
        [["2026-01-05", "-150.00", ""], ["not-a-date", "500.00", ""]],
        header=["Date", "Amount", "Description"],
    )
    response = _import(
        client_a, bank, file_obj, "csv", column_mapping={"date": "Date", "amount": "Amount"},
    )
    assert response.status_code == 400, response.data
    assert "row_3" in response.data
    assert BankStatement.objects.filter(tenant=tenant_a, bank=bank).count() == 0


@pytest.mark.django_db
def test_statement_currency_must_match_bank_currency(tenant_a, client_a):
    bank = _bank(tenant_a, currency="SAR")
    file_obj = _csv_file([["2026-01-05", "100.00", ""]], header=["Date", "Amount", "Description"])
    response = _import(
        client_a, bank, file_obj, "csv", currency="USD",
        column_mapping={"date": "Date", "amount": "Amount"},
    )
    assert response.status_code == 400, response.data


@pytest.mark.django_db
def test_opening_balance_mismatch_with_previous_statement_warns(tenant_a, client_a):
    bank = _bank(tenant_a)
    first = _import(
        client_a, bank, _csv_file([["2026-01-05", "100.00", ""]], header=["Date", "Amount", "Description"]),
        "csv", period_start="2026-01-01", period_end="2026-01-10",
        opening_balance="0.00", closing_balance="100.00",
        column_mapping={"date": "Date", "amount": "Amount"},
    )
    assert first.status_code == 201, first.data

    second = _import(
        client_a, bank, _csv_file([["2026-01-15", "50.00", ""]], header=["Date", "Amount", "Description"]),
        "csv", period_start="2026-01-11", period_end="2026-01-20",
        opening_balance="999.00", closing_balance="1049.00",
        column_mapping={"date": "Date", "amount": "Amount"},
    )
    assert second.status_code == 201, second.data
    # Sprint 6.0 (block 6.0, item 5): this warning's msgid is now
    # translated in the Arabic catalog — LANGUAGE_CODE="ar" is this
    # project's default, so the response carries the Arabic text.
    assert any("الرصيد الافتتاحي" in w for w in second.data["warnings"])


# ---------------------------------------------------------------------
# duplicate / overlap guards
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_duplicate_file_rejected(tenant_a, client_a):
    bank = _bank(tenant_a)

    def make_file():
        return _csv_file([["2026-01-05", "100.00", ""]], header=["Date", "Amount", "Description"])

    first = _import(client_a, bank, make_file(), "csv", column_mapping={"date": "Date", "amount": "Amount"})
    assert first.status_code == 201, first.data

    second = _import(
        client_a, bank, make_file(), "csv", period_start="2026-02-01", period_end="2026-02-28",
        column_mapping={"date": "Date", "amount": "Amount"},
    )
    assert second.status_code == 409, second.data


@pytest.mark.django_db
def test_overlapping_period_different_file_rejected(tenant_a, client_a):
    bank = _bank(tenant_a)
    first = _import(
        client_a, bank, _csv_file([["2026-01-05", "100.00", ""]], header=["Date", "Amount", "Description"]),
        "csv", period_start="2026-01-01", period_end="2026-01-31",
        column_mapping={"date": "Date", "amount": "Amount"},
    )
    assert first.status_code == 201, first.data

    second = _import(
        client_a, bank, _csv_file([["2026-01-20", "999.00", "different"]], header=["Date", "Amount", "Description"]),
        "csv", period_start="2026-01-15", period_end="2026-02-15",
        column_mapping={"date": "Date", "amount": "Amount"},
    )
    assert second.status_code == 409, second.data


# ---------------------------------------------------------------------
# MT940
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_mt940_three_lines_with_correct_signs(tenant_a, client_a):
    bank = _bank(tenant_a, currency="EUR")
    response = _import(
        client_a, bank, _mt940_file(), "mt940", currency="EUR",
        period_start="2026-01-01", period_end="2026-01-31",
        opening_balance="1000.00", closing_balance="1550.00",
    )
    assert response.status_code == 201, response.data
    assert response.data["line_count"] == 3
    amounts = sorted(line["amount"] for line in response.data["lines"])
    assert amounts == ["-150.00", "200.00", "500.00"]
    assert response.data["warnings"] == []


@pytest.mark.django_db
def test_mt940_balance_mismatch_with_entered_values_warns(tenant_a, client_a):
    bank = _bank(tenant_a, currency="EUR")
    response = _import(
        client_a, bank, _mt940_file(MT940_BAD_BALANCE_SAMPLE), "mt940", currency="EUR",
        period_start="2026-01-01", period_end="2026-01-31",
        opening_balance="1000.00", closing_balance="1550.00",
    )
    assert response.status_code == 201, response.data
    # Sprint 6.0 (block 6.0, item 5): Arabic-translated msgid, see the
    # opening-balance test above for the same reasoning.
    assert any("الرصيد الختامي" in w for w in response.data["warnings"])


# ---------------------------------------------------------------------
# original file kept as attachment
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_original_file_saved_as_attachment(tenant_a, client_a):
    bank = _bank(tenant_a)
    response = _import(
        client_a, bank, _csv_file([["2026-01-05", "100.00", ""]], header=["Date", "Amount", "Description"]),
        "csv", column_mapping={"date": "Date", "amount": "Amount"},
    )
    assert response.status_code == 201, response.data
    content_type = ContentType.objects.get_for_model(BankStatement)
    attachment = Attachment.objects.get(
        tenant=tenant_a, content_type=content_type, object_id=response.data["id"]
    )
    assert attachment.category == Attachment.Category.BANK_STATEMENT
    assert attachment.original_name == "statement.csv"


# ---------------------------------------------------------------------
# tenant isolation
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_statements_are_tenant_isolated(tenant_a, client_a, tenant_b, client_b):
    bank_a = _bank(tenant_a)
    response = _import(
        client_a, bank_a, _csv_file([["2026-01-05", "100.00", ""]], header=["Date", "Amount", "Description"]),
        "csv", column_mapping={"date": "Date", "amount": "Amount"},
    )
    assert response.status_code == 201, response.data
    statement_id = response.data["id"]

    cross_get = client_b.get(f"/api/bank-statements/{statement_id}/")
    assert cross_get.status_code == 404

    cross_list = client_b.get(f"/api/bank-statements/?bank={bank_a.id}")
    assert cross_list.data["results"] == [] if isinstance(cross_list.data, dict) else cross_list.data == []

    # Different tenant, own bank with the same id namespace collision
    # isn't possible (UUIDs), but a cross-tenant bank id must still 404
    # rather than leak whether it exists.
    bank_b_import = _import(
        client_b, Bank(id=bank_a.id), _csv_file([["2026-01-05", "1.00", ""]], header=["Date", "Amount", "Description"]),
        "csv", column_mapping={"date": "Date", "amount": "Amount"},
    )
    assert bank_b_import.status_code == 404, bank_b_import.data
