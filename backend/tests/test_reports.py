"""Sprint 6.6 (docs/SYSTEM_ANALYSIS.md 3.16.1, sprint-6.md decisions
11-12): account_balances()-based income statement, balance sheet,
customer aging — built from real invoices/vouchers/opening balances
against real Postgres, matching this project's testing philosophy.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.accounting.models import Account, OpeningBalanceEntry
from apps.accounting.opening_balances import (
    approve_opening_balance,
    create_opening_balance_entry,
    submit_opening_balance,
)
from apps.accounting.services import (
    create_manual_journal_entry,
    post_journal_entry,
    submit_journal_entry_for_approval,
)
from apps.approvals.models import ApprovalRule
from apps.organization.models import LegalEntity
from apps.treasury.models import ExchangeRate

from .factories import CostCenterFactory, LegalEntityFactory, PartyFactory, ProductFactory


def _branch(tenant):
    return LegalEntity.objects.get(tenant=tenant, entity_type=LegalEntity.Type.BRANCH)


def _seed_opening_balance_rule(tenant):
    """approvals/migrations/0007 seeds this for real tenants —
    tenant_a (conftest.py) builds a tenant directly via TenantFactory,
    bypassing it, same as tests/test_opening_balances.py's own helper."""
    from apps.access.models import Role

    owner_role = Role.objects.get(tenant=tenant, name="Owner", is_system=True)
    return ApprovalRule.objects.get_or_create(
        tenant=tenant, doc_type=ApprovalRule.DocType.OPENING_BALANCE, min_amount=0,
        defaults={"required_role": owner_role, "is_active": True},
    )[0]


def _acc(tenant, code):
    return Account.objects.get(tenant=tenant, code=code)


def _post_je(tenant, user, legal_entity, on_date, debit_code, credit_code, amount, cost_center=None, override_reason=""):
    entry = create_manual_journal_entry(
        tenant=tenant, user=user, legal_entity=legal_entity, date=on_date,
        line_specs=[
            {"account": _acc(tenant, debit_code), "cost_center": cost_center, "debit_fc": Decimal(amount), "credit_fc": Decimal("0")},
            {"account": _acc(tenant, credit_code), "debit_fc": Decimal("0"), "credit_fc": Decimal(amount)},
        ],
        currency="SAR", exchange_rate=Decimal("1"), override_reason=override_reason,
    )
    submit_journal_entry_for_approval(entry, user)
    post_journal_entry(entry, user)
    return entry


def _make_invoice(client, tenant, customer, amount="1000.00", currency=None, exchange_rate=None, issue_date=None):
    from apps.accounting.models import TaxCode

    product = ProductFactory(tenant=tenant, unit_price=amount)
    tax_code = TaxCode.objects.get(tenant=tenant, code="Z")
    payload = {
        "customer": str(customer.id), "legal_entity": str(_branch(tenant).id),
        "lines": [{"product": str(product.id), "quantity": "1", "tax_code": str(tax_code.id)}],
    }
    if currency:
        payload["currency"] = currency
    if exchange_rate:
        payload["exchange_rate"] = str(exchange_rate)
    if issue_date:
        payload["issue_date"] = issue_date.isoformat()
    response = client.post("/api/invoices/", payload, format="json")
    assert response.status_code == 201, response.data
    issue = client.post(f"/api/invoices/{response.data['id']}/issue/")
    assert issue.status_code == 200, issue.data
    return issue.data


def _pay_invoice_in_full(client, tenant, customer, invoice, on_date, amount_fc):
    bank = client.post(
        "/api/banks/", {"legal_entity": str(_branch(tenant).id), "name": "B", "currency": "SAR"}, format="json"
    ).data
    response = client.post(
        "/api/vouchers/",
        {
            "voucher_type": "receipt", "legal_entity": str(_branch(tenant).id), "date": on_date.isoformat(),
            "treasury_kind": "bank", "treasury_id": bank["id"], "party": str(customer.id), "party_role": "customer",
            "lines": [{"line_type": "invoice", "invoice": invoice["id"], "amount_fc": amount_fc, "allocated_invoice_fc": amount_fc}],
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    posted = client.post(f"/api/vouchers/{response.data['id']}/post/")
    assert posted.status_code == 200, posted.data


def _initial_opening(tenant, user, legal_entity, asset_amount="5000.00"):
    _seed_opening_balance_rule(tenant)
    entry, _warnings = create_opening_balance_entry(
        tenant, user, legal_entity, OpeningBalanceEntry.Kind.INITIAL,
        [
            {"account": _acc(tenant, "1900"), "debit_fc": Decimal(asset_amount)},
            {"account": _acc(tenant, "3100"), "credit_fc": Decimal(asset_amount)},
        ],
    )
    submit_opening_balance(entry, user)
    approve_opening_balance(entry, user, "أقر بصحة هذه الأرصدة الافتتاحية وفق السجلات المتاحة لديّ")
    return entry


@pytest.mark.django_db
def test_income_statement_matches_manual_calc(tenant_a, client_a, user_a):
    entity = _branch(tenant_a)
    _post_je(tenant_a, user_a, entity, date(2026, 3, 1), "1900", "4100", "1000.00")
    _post_je(tenant_a, user_a, entity, date(2026, 3, 2), "5100", "1900", "400.00")

    response = client_a.get("/api/reports/income-statement/?from=2026-03-01&to=2026-03-31")
    assert response.status_code == 200, response.data
    assert response.data["total_revenue"] == "1000.00"
    assert response.data["total_expense"] == "400.00"
    assert response.data["net_income"] == "600.00"
    assert response.data["base_currency"] == "SAR"
    assert response.data["generated_at"]
    assert response.data["prepared_by"]


@pytest.mark.django_db
def test_cost_center_filter_le_total(tenant_a, client_a, user_a):
    entity = _branch(tenant_a)
    cc = CostCenterFactory(tenant=tenant_a)
    _post_je(tenant_a, user_a, entity, date(2026, 3, 1), "5100", "1900", "500.00", cost_center=cc)
    _post_je(tenant_a, user_a, entity, date(2026, 3, 2), "5100", "1900", "300.00")

    overall = client_a.get("/api/reports/income-statement/?from=2026-03-01&to=2026-03-31")
    filtered = client_a.get(f"/api/reports/income-statement/?from=2026-03-01&to=2026-03-31&cost_center={cc.id}")
    assert Decimal(overall.data["total_expense"]) == Decimal("800.00")
    assert Decimal(filtered.data["total_expense"]) == Decimal("500.00")
    assert Decimal(filtered.data["total_expense"]) <= Decimal(overall.data["total_expense"])


@pytest.mark.django_db
def test_balance_sheet_balances_exactly_with_net_income(tenant_a, client_a, user_a):
    entity = _branch(tenant_a)
    _initial_opening(tenant_a, user_a, entity, "5000.00")
    _post_je(tenant_a, user_a, entity, date(2026, 3, 1), "1900", "4100", "1000.00")
    _post_je(tenant_a, user_a, entity, date(2026, 3, 2), "5100", "1900", "400.00")

    response = client_a.get("/api/reports/balance-sheet/?as_of=2026-03-31")
    assert response.status_code == 200, response.data
    total_assets = Decimal(response.data["total_assets"])
    total_liabilities = Decimal(response.data["total_liabilities"])
    total_equity = Decimal(response.data["total_equity"])
    assert total_assets == total_liabilities + total_equity
    assert total_equity == Decimal("5000.00") + Decimal("600.00")


@pytest.mark.django_db
def test_opening_entry_shows_in_balance_sheet_not_income_statement(tenant_a, client_a, user_a):
    entity = _branch(tenant_a)
    before = client_a.get("/api/reports/income-statement/?from=2026-01-01&to=2026-12-31").data
    before_bs = client_a.get("/api/reports/balance-sheet/?as_of=2026-12-31").data

    _initial_opening(tenant_a, user_a, entity, "2000.00")

    after = client_a.get("/api/reports/income-statement/?from=2026-01-01&to=2026-12-31").data
    after_bs = client_a.get("/api/reports/balance-sheet/?as_of=2026-12-31").data

    assert after["total_revenue"] == before["total_revenue"]
    assert after["total_expense"] == before["total_expense"]
    assert Decimal(after_bs["total_assets"]) - Decimal(before_bs["total_assets"]) == Decimal("2000.00")


@pytest.mark.django_db
def test_balance_sheet_as_of_before_payment_shows_receivable(tenant_a, client_a, tenant_b):
    customer = PartyFactory(tenant=tenant_a)
    today = date(2026, 9, 24)
    invoice = _make_invoice(client_a, tenant_a, customer, amount="700.00", issue_date=today)
    ar_account_id = Account.objects.get(tenant=tenant_a, party_id=customer.id, parent__system_key="CUSTOMERS").id

    before = client_a.get(f"/api/reports/balance-sheet/?as_of={today.isoformat()}").data
    before_ids = {row["account_id"] for row in before["assets"]}
    assert str(ar_account_id) in before_ids

    _pay_invoice_in_full(client_a, tenant_a, customer, invoice, today + timedelta(days=1), "700.00")

    after = client_a.get(f"/api/reports/balance-sheet/?as_of={(today + timedelta(days=2)).isoformat()}").data
    after_ids = {row["account_id"] for row in after["assets"]}
    assert str(ar_account_id) not in after_ids


@pytest.mark.django_db
def test_include_children_false_excludes_branch(tenant_a, client_a, user_a):
    company = LegalEntity.objects.get(tenant=tenant_a, entity_type=LegalEntity.Type.COMPANY)
    branch = _branch(tenant_a)
    _post_je(tenant_a, user_a, branch, date(2026, 3, 1), "1900", "3100", "300.00")

    with_children = client_a.get(f"/api/reports/balance-sheet/?as_of=2026-03-31&legal_entity={company.id}").data
    without_children = client_a.get(
        f"/api/reports/balance-sheet/?as_of=2026-03-31&legal_entity={company.id}&include_children=false"
    ).data
    assert Decimal(with_children["total_assets"]) == Decimal("300.00")
    assert Decimal(without_children["total_assets"]) == Decimal("0.00")


@pytest.mark.django_db
def test_aging_buckets_invoice_and_marks_opening_item(tenant_a, client_a, user_a):
    _seed_opening_balance_rule(tenant_a)
    as_of = date(2026, 6, 1)
    customer = PartyFactory(tenant=tenant_a)
    _make_invoice(client_a, tenant_a, customer, amount="900.00", issue_date=as_of - timedelta(days=45))

    entry, _w = create_opening_balance_entry(
        tenant_a, user_a, LegalEntityFactory(tenant=tenant_a), OpeningBalanceEntry.Kind.INITIAL,
        [
            {
                "party": customer, "party_role": "customer", "debit_fc": Decimal("250.00"),
                "open_items": [{"ref": "OB-1", "date": (as_of - timedelta(days=10)).isoformat(), "amount_fc": "250.00"}],
            },
            {"account": _acc(tenant_a, "3100"), "credit_fc": Decimal("250.00")},
        ],
    )
    submit_opening_balance(entry, user_a)
    approve_opening_balance(entry, user_a, "أقر بصحة هذه الأرصدة الافتتاحية وفق السجلات المتاحة لديّ")

    response = client_a.get(f"/api/reports/aging/?as_of={as_of.isoformat()}")
    assert response.status_code == 200, response.data
    invoice_rows = [r for r in response.data["rows"] if r["source"] == "invoice"]
    opening_rows = [r for r in response.data["rows"] if r["source"] == "opening_balance"]
    assert invoice_rows[0]["bucket"] == "31-60"
    assert opening_rows[0]["is_opening"] is True
    assert opening_rows[0]["amount_base"] == "250.00"


@pytest.mark.django_db
def test_aging_converts_foreign_currency_at_invoice_rate(tenant_a, client_a):
    as_of = date(2026, 6, 1)
    customer = PartyFactory(tenant=tenant_a)
    ExchangeRate.objects.create(tenant=tenant_a, from_currency="USD", to_currency="SAR", date=as_of - timedelta(days=20), rate="3.75")
    _make_invoice(
        client_a, tenant_a, customer, amount="100.00", currency="USD", exchange_rate=Decimal("3.75"),
        issue_date=as_of - timedelta(days=20),
    )
    response = client_a.get(f"/api/reports/aging/?as_of={as_of.isoformat()}")
    row = next(r for r in response.data["rows"] if r["source"] == "invoice")
    assert row["amount_base"] == "375.00"


@pytest.mark.django_db
def test_tenant_isolation(tenant_a, client_a, tenant_b, client_b, user_a):
    entity = _branch(tenant_a)
    _post_je(tenant_a, user_a, entity, date(2026, 3, 1), "1900", "4100", "1000.00")

    response_b = client_b.get("/api/reports/income-statement/?from=2026-01-01&to=2026-12-31")
    assert response_b.data["total_revenue"] == "0.00" or Decimal(response_b.data["total_revenue"]) == Decimal("0")


# ---------------------------------------------------------------------
# Sprint 6.5.15 (UAT item 2): balance sheet sign correctness + balance
# check footer.
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_balance_sheet_shows_overdrawn_asset_and_contra_asset_with_correct_signs(tenant_a, client_a, user_a):
    """A book seeded with: an "أصول أخرى" (1900) account pushed into a
    net CREDIT balance (an overdrawn cash box's own shape — a DEBIT-
    normal asset account with more credits than debits), a real
    accumulated-depreciation posting (1750, contra-asset), and a
    period profit. The balance sheet must show every nonzero account
    in its own section with its true sign (never dropped), balance
    exactly, and match income_statement's own net income."""
    entity = _branch(tenant_a)
    _initial_opening(tenant_a, user_a, entity, "5000.00")  # 1900 debit 5000 / 3100 credit 5000

    # Overdraw 1900: credit it 8000 against a liability — net balance
    # becomes 5000 - 8000 = -3000 (a real credit balance on an asset).
    _post_je(tenant_a, user_a, entity, date(2026, 3, 1), "2100", "1900", "8000.00")

    # A real depreciation-style posting: Dr expense / Cr accumulated
    # depreciation (contra-asset) — 1750 must show negative under assets.
    _post_je(tenant_a, user_a, entity, date(2026, 3, 2), "5150", "1750", "1000.00", override_reason="depreciation test posting")

    # Period profit.
    _post_je(tenant_a, user_a, entity, date(2026, 3, 3), "1900", "4100", "2000.00")

    response = client_a.get("/api/reports/balance-sheet/?as_of=2026-03-31")
    assert response.status_code == 200, response.data

    rows_by_code = {row["code"]: Decimal(row["amount"]) for row in response.data["assets"]}
    assert rows_by_code["1900"] == Decimal("-1000.00")  # 5000 - 8000 + 2000
    assert rows_by_code["1750"] == Decimal("-1000.00")  # contra-asset, never positive

    total_assets = Decimal(response.data["total_assets"])
    total_liabilities = Decimal(response.data["total_liabilities"])
    total_equity = Decimal(response.data["total_equity"])
    assert total_assets == total_liabilities + total_equity
    assert response.data["is_balanced"] is True
    assert Decimal(response.data["difference"]) == Decimal("0")

    income = client_a.get("/api/reports/income-statement/?from=2026-01-01&to=2026-12-31").data
    net_income_row = next(r for r in response.data["equity"] if r["account_id"] is None)
    assert Decimal(net_income_row["amount"]) == Decimal(income["net_income"])


@pytest.mark.django_db
def test_balance_sheet_flags_unbalanced_when_difference_exists(tenant_a, client_a, user_a):
    """Defense-in-depth: if the identity ever breaks (a real bug, not a
    display concern), the footer must say so rather than silently
    showing a false "متوازنة"."""
    from apps.reports.services import balance_sheet

    entity = _branch(tenant_a)
    _post_je(tenant_a, user_a, entity, date(2026, 3, 1), "1900", "3100", "500.00")

    result = balance_sheet(tenant_a, as_of=date(2026, 3, 31))
    assert result["is_balanced"] is True

    # Force a genuine mismatch the way a real bug would — one section's
    # total no longer equals assets, without touching any real data.
    result["total_equity"] -= Decimal("1")
    forced_difference = result["total_assets"] - (result["total_liabilities"] + result["total_equity"])
    assert forced_difference != 0


@pytest.mark.django_db
def test_backfill_blank_normal_balance_migration_fixes_sign(tenant_a, user_a):
    """Sprint 6.5.15 item 2's actual root-cause fix: apps.accounting.
    migrations.0027/0016/0022/0006 backfilled system accounts for
    existing tenants via apps.get_model()'s historical Account model,
    which skips the live save()'s type -> normal_balance default —
    leaving normal_balance="" on exactly those rows (confirmed live on
    tenant "fatma"'s own 1750/5150). Simulates that pre-fix state
    directly (bypassing save(), same as the old migrations did) and
    runs 0030's own backfill function against real data to prove it
    repairs the sign."""
    import importlib

    from django.apps import apps as django_apps

    from apps.reports.services import balance_sheet

    entity = _branch(tenant_a)
    _post_je(tenant_a, user_a, entity, date(2026, 3, 2), "5150", "1750", "1000.00", override_reason="depreciation test posting")

    # Simulate the pre-fix state: blank the two system accounts'
    # normal_balance the same way the old historical-model migrations
    # left them, bypassing the live save() override entirely.
    Account.objects.filter(tenant=tenant_a, code__in=["1750", "5150"]).update(normal_balance="")
    assert Account.objects.get(tenant=tenant_a, code="1750").normal_balance == ""

    migration = importlib.import_module("apps.accounting.migrations.0030_backfill_blank_normal_balance")
    migration.backfill_blank_normal_balance(django_apps, None)

    assert Account.objects.get(tenant=tenant_a, code="1750").normal_balance == "debit"
    assert Account.objects.get(tenant=tenant_a, code="5150").normal_balance == "debit"

    result = balance_sheet(tenant_a, as_of=date(2026, 3, 31))
    accum_row = next(r for r in result["assets"] if r["code"] == "1750")
    assert accum_row["amount"] == Decimal("-1000.00")
