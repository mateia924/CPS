"""Sprint 6.9: two net-new read-only surfaces —
GET /api/reconciliation-dashboard/ (one row per bank, a debt
from 5.5.2) and the new dashboard-summary fields (current period, due
recurring installments, fiscal-year-ending-soon, opening-not-approved).
"""

import datetime
import json

import pytest

from apps.accounting.models import TaxCode
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


def _deposit(client, tenant, bank, amount, date="2026-01-05"):
    tax_code = TaxCode.objects.get(tenant=tenant, code="Z")
    from apps.accounting.models import Account

    revenue = Account.objects.filter(tenant=tenant, code="4100").first()
    response = client.post(
        "/api/vouchers/",
        {
            "voucher_type": "receipt", "legal_entity": str(_branch(tenant).id), "date": date,
            "treasury_kind": "bank", "treasury_id": str(bank.id), "payee_name": "Depositor",
            "lines": [{"line_type": "account", "account": str(revenue.id), "tax_code": str(tax_code.id), "amount_fc": amount}],
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


@pytest.mark.django_db
def test_reconciliation_dashboard_one_row_per_active_bank(tenant_a, client_a):
    bank1 = _bank(tenant_a)
    bank2 = _bank(tenant_a)
    _deposit(client_a, tenant_a, bank1, "500.00")
    imported = _import_statement(client_a, bank1, [("2026-01-05", "500.00", "Deposit")])
    assert imported.status_code == 201, imported.data

    response = client_a.get("/api/reconciliation-dashboard/")
    assert response.status_code == 200, response.data
    by_id = {row["bank_id"]: row for row in response.data}
    assert str(bank1.id) in by_id
    assert str(bank2.id) in by_id
    row1 = by_id[str(bank1.id)]
    assert row1["has_statement"] is True
    assert row1["reconciled_ratio"] == 1.0
    assert row1["unmatched_statement_items"] == 0
    row2 = by_id[str(bank2.id)]
    assert row2["has_statement"] is False
    assert row2["reconciled_ratio"] == 0.0


@pytest.mark.django_db
def test_reconciliation_dashboard_unmatched_items_counted(tenant_a, client_a):
    bank = _bank(tenant_a)
    imported = _import_statement(client_a, bank, [("2026-01-05", "777.00", "Unmatched deposit")])
    assert imported.status_code == 201, imported.data

    response = client_a.get("/api/reconciliation-dashboard/")
    assert response.status_code == 200, response.data
    row = next(r for r in response.data if r["bank_id"] == str(bank.id))
    assert row["unmatched_statement_items"] == 1
    assert row["reconciled_ratio"] == 0.0


@pytest.mark.django_db
def test_reconciliation_dashboard_tenant_isolation(tenant_a, tenant_b, client_a, client_b):
    _bank(tenant_a)
    response = client_b.get("/api/reconciliation-dashboard/")
    assert response.status_code == 200
    assert response.data == []


@pytest.mark.django_db
def test_dashboard_summary_current_period_and_alerts(tenant_a, client_a):
    response = client_a.get("/api/dashboard/summary/")
    assert response.status_code == 200, response.data
    data = response.data
    assert data["current_period"] is not None
    assert data["current_period"]["status"] == "open"
    assert data["due_recurring_installments"] == 0
    # tenant_a's fiscal year (conftest.py) starts 2026-01-01, far from
    # today (2026-09-24) — the 30-day-horizon alert must stay quiet.
    assert data["fiscal_year_ending_soon"] is None
    # create_default_legal_entities (conftest.py) never sets
    # opening_approved_at, so the tenant's one active branch is flagged.
    assert len(data["opening_not_approved"]) >= 1


@pytest.mark.django_db
def test_dashboard_summary_fiscal_year_ending_soon(tenant_a, client_a):
    from django.utils import timezone

    from apps.accounting.models import FiscalYear

    year = FiscalYear.objects.get(tenant=tenant_a, name="2026")
    today = timezone.localdate()
    year.end_date = today + datetime.timedelta(days=10)
    year.save(update_fields=["end_date"])

    response = client_a.get("/api/dashboard/summary/")
    assert response.status_code == 200, response.data
    alert = response.data["fiscal_year_ending_soon"]
    assert alert is not None
    assert alert["days_left"] == 10
    assert alert["next_year_created"] is False
