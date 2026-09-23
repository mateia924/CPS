"""Sprint 5.5 (block 5.5.1, v2 decision 5): bank statement import —
CSV/Excel (column-mapped) and MT940 (the `mt-940` PyPI package, import
name `mt940` — not the unrelated older package that shares the literal
name `mt940` on PyPI). CAMT.053 is explicitly out of scope this sprint
(v2 "ما تغيّر" #1) — `parse_statement_file` below is the one seam a
future CAMT parser plugs into without touching the matching engine
(block 5.5.2) at all, which only ever sees the common `ParsedLine`
shape.
"""

import csv
import datetime
import io
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import openpyxl
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

# Explicit, tried-in-order date formats — "صيغ تاريخ متعددة صراحة"
# (v2 block 5.5.1), never a guessing/fuzzy parser.
_DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y"]


@dataclass
class ParsedLine:
    date: datetime.date
    # Signed: positive = deposit/credit, negative = withdrawal/debit —
    # the same convention as BankStatementLine.amount.
    amount: Decimal
    description: str = ""
    reference: str = ""


class StatementParseError(ValidationError):
    """`message_dict` carries one entry per bad row
    (`{"row_<n>": ["..."]}`) so the view can report every problem at
    once — the whole batch is rejected, never partially imported
    (v2 decision 5: "لا استيراد جزئي صامت")."""


def _parse_date(raw):
    text = str(raw).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    if isinstance(raw, datetime.date):
        return raw
    return None


def _parse_decimal(raw):
    if raw is None or raw == "":
        return None
    if isinstance(raw, Decimal):
        return raw
    if isinstance(raw, (int, float)):
        return Decimal(str(raw))
    text = str(raw).strip().replace(",", "")
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _rows_from_csv(file_obj):
    # Read the raw bytes into a separate StringIO rather than wrapping
    # `file_obj` itself in a TextIOWrapper — a TextIOWrapper closes its
    # underlying buffer on garbage collection, which would close the
    # caller's still-in-use UploadedFile the moment this function
    # returns (a real bug caught by every test below that re-reads
    # `file_obj` afterward, e.g. to save it as an Attachment).
    content = file_obj.read()
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(content))
    return list(reader)


def _rows_from_xlsx(file_obj):
    workbook = openpyxl.load_workbook(file_obj, data_only=True, read_only=True)
    sheet = workbook.worksheets[0]
    return [list(row) for row in sheet.iter_rows(values_only=True)]


def parse_csv_xlsx(file_obj, import_format, column_mapping):
    """`column_mapping`: {"date": "<header>", "amount": "<header>"} or
    {"date": "<header>", "debit": "<header>", "credit": "<header>"},
    plus optional "description"/"reference". The header row (row 1)
    supplies the column names `column_mapping` refers to."""
    if not column_mapping.get("date") or not (
        column_mapping.get("amount") or (column_mapping.get("debit") and column_mapping.get("credit"))
    ):
        raise StatementParseError(
            {"column_mapping": [str(_("Map at least a date column and an amount (or debit/credit) column."))]}
        )

    rows = _rows_from_csv(file_obj) if import_format == "csv" else _rows_from_xlsx(file_obj)
    if len(rows) < 2:
        raise StatementParseError({"file": [str(_("The file has no data rows."))]})

    header = [str(cell).strip() if cell is not None else "" for cell in rows[0]]
    try:
        column_index = {key: header.index(value) for key, value in column_mapping.items() if value}
    except ValueError as exc:
        raise StatementParseError({"column_mapping": [str(_("Column not found in the file header: %s")) % exc]})

    def _cell(row, key):
        idx = column_index.get(key)
        if idx is None or idx >= len(row):
            return None
        return row[idx]

    lines = []
    errors = {}
    for row_no, row in enumerate(rows[1:], start=2):
        if all(cell in (None, "") for cell in row):
            continue
        date = _parse_date(_cell(row, "date"))
        if date is None:
            errors[f"row_{row_no}"] = [str(_("Invalid or unrecognized date."))]
            continue
        if "amount" in column_index:
            amount = _parse_decimal(_cell(row, "amount"))
            if amount is None:
                errors[f"row_{row_no}"] = [str(_("Invalid amount."))]
                continue
        else:
            debit = _parse_decimal(_cell(row, "debit")) or Decimal("0")
            credit = _parse_decimal(_cell(row, "credit")) or Decimal("0")
            amount = credit - debit
        description = str(_cell(row, "description") or "")
        reference = str(_cell(row, "reference") or "")
        lines.append(ParsedLine(date=date, amount=amount, description=description, reference=reference))

    if errors:
        raise StatementParseError(errors)
    return lines


def parse_mt940(file_obj):
    import mt940

    content = file_obj.read()
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")
    try:
        transactions = mt940.parse(io.StringIO(content))
    except Exception as exc:  # mt940 raises plain Exception/ValueError on malformed input
        raise StatementParseError({"file": [str(_("Could not parse MT940 file: %s")) % exc]})

    lines = []
    for index, transaction in enumerate(transactions, start=1):
        data = transaction.data
        amount = data["amount"].amount  # already signed (mt940's own C/D convention)
        date = data["date"]
        if not isinstance(date, datetime.date):
            raise StatementParseError({f"row_{index}": [str(_("Invalid date in MT940 entry."))]})
        lines.append(
            ParsedLine(
                date=datetime.date(date.year, date.month, date.day),
                amount=amount,
                description=data.get("transaction_details", "") or "",
                reference=data.get("customer_reference", "") or "",
            )
        )
    return lines, transactions.data


PARSERS = {"csv": parse_csv_xlsx, "xlsx": parse_csv_xlsx, "mt940": parse_mt940}


def parse_statement_file(file_obj, import_format, column_mapping=None):
    """Returns (lines: list[ParsedLine], mt940_meta: dict | None) — the
    second element is only populated for MT940 (opening/closing balance
    from the file itself, compared against the user's input by the
    caller for the v2 decision-5 continuity warning)."""
    parser = PARSERS.get(import_format)
    if parser is None:
        raise StatementParseError({"format": [str(_("Unsupported import format."))]})
    if import_format == "mt940":
        return parser(file_obj)
    return parser(file_obj, import_format, column_mapping or {}), None
