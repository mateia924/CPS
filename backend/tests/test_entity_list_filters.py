"""Sprint 6.5.18 (UAT item 5): assets/banks/cash-boxes/custodies/
vouchers/journal-entries/invoices all show every legal entity the user
can access by default — the list itself is never narrowed to the
user's own default entity. Each list's own OPTIONAL `?legal_entity=`
query param, when the caller does pass it, narrows within whatever the
endpoint already allows (accessible entities for vouchers/journal-
entries/invoices, the whole tenant for assets/banks/cash-boxes/
custodies — matching each viewset's own, pre-existing scope). Real
HTTP API + real Postgres throughout (§11)."""

from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounting.models import Account, TaxCode
from apps.accounting.services import (
    create_manual_journal_entry,
    post_journal_entry,
    submit_journal_entry_for_approval,
)
from apps.organization.models import LegalEntity
from apps.parties.models import PartyRole

from .factories import AssetFactory, LegalEntityFactory, PartyFactory, ProductFactory


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def owner_client(user_a):
    return _client(user_a)


@pytest.fixture
def company(tenant_a):
    return LegalEntity.objects.get(tenant=tenant_a, entity_type=LegalEntity.Type.COMPANY)


@pytest.fixture
def branch_a(tenant_a, company):
    return LegalEntity.objects.get(tenant=tenant_a, entity_type=LegalEntity.Type.BRANCH)


@pytest.fixture
def branch_b(tenant_a, company):
    return LegalEntityFactory(
        tenant=tenant_a, entity_type=LegalEntity.Type.BRANCH, parent=company, code="BR-B", name="الفرع الثاني",
    )


def test_assets_list_shows_both_entities_by_default_and_narrows_when_asked(
    tenant_a, owner_client, branch_a, branch_b
):
    asset_1 = AssetFactory(tenant=tenant_a, legal_entity=branch_a, purchase_date="2026-01-01", purchase_cost="1000.00")
    asset_2 = AssetFactory(tenant=tenant_a, legal_entity=branch_b, purchase_date="2026-01-01", purchase_cost="2000.00")

    everything = owner_client.get("/api/assets/")
    ids = {row["id"] for row in everything.data["results"]}
    assert {str(asset_1.id), str(asset_2.id)} <= ids

    narrowed = owner_client.get(f"/api/assets/?legal_entity={branch_b.id}")
    narrowed_ids = {row["id"] for row in narrowed.data["results"]}
    assert str(asset_2.id) in narrowed_ids
    assert str(asset_1.id) not in narrowed_ids


def test_banks_list_shows_both_entities_by_default_and_narrows_when_asked(tenant_a, owner_client, branch_a, branch_b):
    bank_1 = owner_client.post(
        "/api/banks/", {"legal_entity": str(branch_a.id), "name": "Bank A", "currency": "SAR"}, format="json",
    ).data
    bank_2 = owner_client.post(
        "/api/banks/", {"legal_entity": str(branch_b.id), "name": "Bank B", "currency": "SAR"}, format="json",
    ).data

    everything = owner_client.get("/api/banks/")
    ids = {row["id"] for row in everything.data["results"]}
    assert {bank_1["id"], bank_2["id"]} <= ids

    narrowed = owner_client.get(f"/api/banks/?legal_entity={branch_b.id}")
    narrowed_ids = {row["id"] for row in narrowed.data["results"]}
    assert bank_2["id"] in narrowed_ids
    assert bank_1["id"] not in narrowed_ids


def test_cash_boxes_list_shows_both_entities_by_default_and_narrows_when_asked(
    tenant_a, owner_client, branch_a, branch_b
):
    box_1 = owner_client.post(
        "/api/cash-boxes/", {"legal_entity": str(branch_a.id), "name": "Box A", "currency": "SAR"}, format="json",
    ).data
    box_2 = owner_client.post(
        "/api/cash-boxes/", {"legal_entity": str(branch_b.id), "name": "Box B", "currency": "SAR"}, format="json",
    ).data

    everything = owner_client.get("/api/cash-boxes/")
    ids = {row["id"] for row in everything.data["results"]}
    assert {box_1["id"], box_2["id"]} <= ids

    narrowed = owner_client.get(f"/api/cash-boxes/?legal_entity={branch_b.id}")
    narrowed_ids = {row["id"] for row in narrowed.data["results"]}
    assert box_2["id"] in narrowed_ids
    assert box_1["id"] not in narrowed_ids


def test_custodies_list_shows_both_entities_by_default_and_narrows_when_asked(
    tenant_a, owner_client, branch_a, branch_b
):
    employee_1 = PartyFactory(tenant=tenant_a)
    PartyRole.objects.create(party=employee_1, role=PartyRole.Role.EMPLOYEE)
    employee_2 = PartyFactory(tenant=tenant_a)
    PartyRole.objects.create(party=employee_2, role=PartyRole.Role.EMPLOYEE)

    custody_1 = owner_client.post(
        "/api/custodies/",
        {"legal_entity": str(branch_a.id), "employee": str(employee_1.id), "name": "Custody A", "currency": "SAR"},
        format="json",
    ).data
    custody_2 = owner_client.post(
        "/api/custodies/",
        {"legal_entity": str(branch_b.id), "employee": str(employee_2.id), "name": "Custody B", "currency": "SAR"},
        format="json",
    ).data

    everything = owner_client.get("/api/custodies/")
    ids = {row["id"] for row in everything.data["results"]}
    assert {custody_1["id"], custody_2["id"]} <= ids

    narrowed = owner_client.get(f"/api/custodies/?legal_entity={branch_b.id}")
    narrowed_ids = {row["id"] for row in narrowed.data["results"]}
    assert custody_2["id"] in narrowed_ids
    assert custody_1["id"] not in narrowed_ids


def test_journal_entries_list_shows_both_entities_by_default_and_narrows_when_asked(
    tenant_a, owner_client, user_a, branch_a, branch_b
):
    revenue = Account.objects.filter(tenant=tenant_a, code="4100").first()
    expense = Account.objects.filter(tenant=tenant_a, code="5100").first()

    entry_1 = create_manual_journal_entry(
        tenant=tenant_a, user=user_a, legal_entity=branch_a, date=date(2026, 1, 5),
        line_specs=[
            {"account": revenue, "debit_fc": Decimal("0"), "credit_fc": Decimal("100.00")},
            {"account": expense, "debit_fc": Decimal("100.00"), "credit_fc": Decimal("0")},
        ],
        currency="SAR", exchange_rate=Decimal("1"), override_reason="اختبار",
    )
    submit_journal_entry_for_approval(entry_1, user_a)
    post_journal_entry(entry_1, user_a)

    entry_2 = create_manual_journal_entry(
        tenant=tenant_a, user=user_a, legal_entity=branch_b, date=date(2026, 1, 5),
        line_specs=[
            {"account": revenue, "debit_fc": Decimal("0"), "credit_fc": Decimal("200.00")},
            {"account": expense, "debit_fc": Decimal("200.00"), "credit_fc": Decimal("0")},
        ],
        currency="SAR", exchange_rate=Decimal("1"), override_reason="اختبار",
    )
    submit_journal_entry_for_approval(entry_2, user_a)
    post_journal_entry(entry_2, user_a)

    everything = owner_client.get("/api/journal-entries/")
    ids = {row["id"] for row in everything.data["results"]}
    assert {str(entry_1.id), str(entry_2.id)} <= ids

    narrowed = owner_client.get(f"/api/journal-entries/?legal_entity={branch_b.id}")
    narrowed_ids = {row["id"] for row in narrowed.data["results"]}
    assert str(entry_2.id) in narrowed_ids
    assert str(entry_1.id) not in narrowed_ids


def test_vouchers_list_shows_both_entities_by_default_and_narrows_when_asked(
    tenant_a, owner_client, branch_a, branch_b
):
    box_a = owner_client.post(
        "/api/cash-boxes/", {"legal_entity": str(branch_a.id), "name": "Box A", "currency": "SAR"}, format="json",
    ).data
    box_b = owner_client.post(
        "/api/cash-boxes/", {"legal_entity": str(branch_b.id), "name": "Box B", "currency": "SAR"}, format="json",
    ).data
    revenue = Account.objects.filter(tenant=tenant_a, code="4100").first()
    tax_code = TaxCode.objects.get(tenant=tenant_a, code="Z")

    voucher_1 = owner_client.post(
        "/api/vouchers/",
        {
            "voucher_type": "receipt", "legal_entity": str(branch_a.id), "date": "2026-01-05",
            "treasury_kind": "cash_box", "treasury_id": box_a["id"], "payee_name": "A",
            "lines": [{"line_type": "account", "account": str(revenue.id), "tax_code": str(tax_code.id), "amount_fc": "100.00"}],
        },
        format="json",
    ).data
    voucher_2 = owner_client.post(
        "/api/vouchers/",
        {
            "voucher_type": "receipt", "legal_entity": str(branch_b.id), "date": "2026-01-05",
            "treasury_kind": "cash_box", "treasury_id": box_b["id"], "payee_name": "B",
            "lines": [{"line_type": "account", "account": str(revenue.id), "tax_code": str(tax_code.id), "amount_fc": "200.00"}],
        },
        format="json",
    ).data

    everything = owner_client.get("/api/vouchers/")
    ids = {row["id"] for row in everything.data["results"]}
    assert {voucher_1["id"], voucher_2["id"]} <= ids

    narrowed = owner_client.get(f"/api/vouchers/?legal_entity={branch_b.id}")
    narrowed_ids = {row["id"] for row in narrowed.data["results"]}
    assert voucher_2["id"] in narrowed_ids
    assert voucher_1["id"] not in narrowed_ids


def test_invoices_list_shows_both_entities_by_default_and_narrows_when_asked(
    tenant_a, owner_client, branch_a, branch_b
):
    customer = PartyFactory(tenant=tenant_a)
    tax_code = TaxCode.objects.get(tenant=tenant_a, code="Z")
    product = ProductFactory(tenant=tenant_a, unit_price="100.00")

    invoice_1 = owner_client.post(
        "/api/invoices/",
        {
            "customer": str(customer.id), "legal_entity": str(branch_a.id),
            "lines": [{"product": str(product.id), "quantity": "1", "tax_code": str(tax_code.id)}],
        },
        format="json",
    ).data
    invoice_2 = owner_client.post(
        "/api/invoices/",
        {
            "customer": str(customer.id), "legal_entity": str(branch_b.id),
            "lines": [{"product": str(product.id), "quantity": "1", "tax_code": str(tax_code.id)}],
        },
        format="json",
    ).data

    everything = owner_client.get("/api/invoices/")
    ids = {row["id"] for row in everything.data["results"]}
    assert {invoice_1["id"], invoice_2["id"]} <= ids

    narrowed = owner_client.get(f"/api/invoices/?legal_entity={branch_b.id}")
    narrowed_ids = {row["id"] for row in narrowed.data["results"]}
    assert invoice_2["id"] in narrowed_ids
    assert invoice_1["id"] not in narrowed_ids
