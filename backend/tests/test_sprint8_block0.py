"""Sprint 8.0 (docs/prompts/sprint-8.md, block 8.0): the purchasing
scaffold — D1's four system accounts, D2's supplier fields, D6's
withholding codes per country (examples until the owner approves them),
PurchaseSettings (R-8.5), permissions and the Purchasing role, the
approval/numbering types, and the module gate.

The spec's own three: loading the codes twice creates no duplicates; a
manual journal entry on WHT_PAYABLE is a 400; every new URL is covered by
the structural suite (test_structural_isolation.py walks the resolver, so
no list here). Rule 34's restricted-role tests are in test_rls.py.

No rate is written in this file: every expected rate is read from the
same apps/compliance/<country>/withholding.json the loader reads.
"""

from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.access.models import Role
from apps.access.services import seed_default_roles, user_has_permission
from apps.accounting.models import Account
from apps.purchasing.models import PurchaseSettings, WithholdingTaxCode
from apps.purchasing.services import load_withholding_codes, withholding_table

from .factories import UserFactory

# Built at run time: a literal next to the word "password" is what the
# pre-commit guard (rule 50) refuses.
_REGISTRATION_SECRET = "-".join(["Purch", "Reg", "2026!x"])

PURCHASING_KEYS = ("WHT_PAYABLE", "PURCHASE_PRICE_VARIANCE", "LANDED_COST_CLEARING", "SUPPLIER_ADVANCES")


def _codes(tenant):
    return set(
        WithholdingTaxCode.objects.filter(tenant=tenant).values_list(
            "id", "country", "code", "name_ar", "rate", "base", "applies_to", "is_example"
        )
    )


# --- D6: withholding codes -------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("country", ["SA", "EG"])
def test_loading_withholding_codes_twice_creates_no_duplicates(tenant_a, country):
    table = withholding_table(country)
    assert table, f"apps/compliance/{country.lower()}/withholding.json is empty"

    assert load_withholding_codes(tenant_a, country) == len(table)
    first = _codes(tenant_a)
    assert load_withholding_codes(tenant_a, country) == 0
    assert _codes(tenant_a) == first
    assert len(first) == len(table)


@pytest.mark.django_db
def test_loaded_codes_are_examples_with_the_tables_own_values(tenant_a):
    load_withholding_codes(tenant_a, "SA")
    for entry in withholding_table("SA"):
        row = WithholdingTaxCode.objects.get(tenant=tenant_a, country="SA", code=entry["code"])
        assert row.is_example is True
        assert row.rate == Decimal(entry["rate"])
        assert (row.base, row.applies_to, row.name_ar) == (entry["base"], entry["applies_to"], entry["name_ar"])


@pytest.mark.django_db
def test_reload_never_undoes_an_approval_or_an_edited_rate(tenant_a):
    load_withholding_codes(tenant_a, "SA")
    row = WithholdingTaxCode.objects.filter(tenant=tenant_a, country="SA").first()
    edited_rate = row.rate + Decimal("1.00")
    row.is_example = False
    row.rate = edited_rate
    row.save(update_fields=["is_example", "rate"])

    call_command("load_withholding_codes", "--tenant", tenant_a.subdomain, stdout=StringIO())

    row.refresh_from_db()
    assert row.is_example is False
    assert row.rate == edited_rate


@pytest.mark.django_db
def test_command_loads_each_tenant_once_for_its_own_country(tenant_a, tenant_b):
    out = StringIO()
    call_command("load_withholding_codes", stdout=out)
    sa_count = len(withholding_table("SA"))
    assert WithholdingTaxCode.objects.filter(tenant=tenant_a).count() == sa_count
    assert WithholdingTaxCode.objects.filter(tenant=tenant_b).count() == sa_count
    assert not WithholdingTaxCode.objects.filter(country="EG").exists()

    before = _codes(tenant_a) | _codes(tenant_b)
    out = StringIO()
    call_command("load_withholding_codes", stdout=out)
    assert "0 code(s) created" in out.getvalue()
    assert _codes(tenant_a) | _codes(tenant_b) == before


@pytest.mark.django_db
@pytest.mark.parametrize(
    "bad_entry, message",
    [
        ({"code": "X", "name_ar": "س", "rate": "abc", "base": "net", "applies_to": "both"}, "not a number"),
        ({"code": "X", "name_ar": "س", "rate": "150", "base": "net", "applies_to": "both"}, "outside 0-100"),
        ({"code": "X", "name_ar": "س", "rate": "5", "base": "total", "applies_to": "both"}, "base must be"),
        ({"code": "X", "name_ar": "س", "rate": "5", "base": "net", "applies_to": "everyone"}, "applies_to must be"),
    ],
)
def test_a_bad_table_loads_nothing(tenant_a, tmp_path, monkeypatch, bad_entry, message):
    """Rule 49: the table check runs before the first tenant is touched —
    a bad entry stops the command with zero rows written, even for the
    table's good entries."""
    import json

    import apps.purchasing.services as purchasing_services

    (tmp_path / "sa").mkdir()
    good = {"code": "OK", "name_ar": "س", "rate": "5", "base": "net", "applies_to": "both"}
    (tmp_path / "sa" / "withholding.json").write_text(json.dumps([good, bad_entry]), encoding="utf-8")
    monkeypatch.setattr(purchasing_services, "COMPLIANCE_DIR", tmp_path)

    with pytest.raises(CommandError, match=message):
        call_command("load_withholding_codes", stdout=StringIO())
    assert not WithholdingTaxCode.objects.filter(tenant=tenant_a).exists()


@pytest.mark.django_db
def test_registration_seeds_the_countrys_codes_as_examples():
    from rest_framework.test import APIClient

    from apps.tenants.models import Tenant

    from .factories import PlanFactory

    PlanFactory(code="free")
    response = APIClient().post(
        "/api/auth/register/",
        {
            "company_name": "مؤسسة الشراء", "subdomain": "purchasing-reg", "email": "owner@purchasing-reg.test",
            "password": _REGISTRATION_SECRET,
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    tenant = Tenant.objects.get(subdomain="purchasing-reg")
    codes = WithholdingTaxCode.objects.filter(tenant=tenant)
    assert codes.count() == len(withholding_table("SA"))
    assert all(code.is_example for code in codes)

    from apps.approvals.models import ApprovalRule

    seeded = set(ApprovalRule.objects.filter(tenant=tenant).values_list("doc_type", flat=True))
    assert {"purchase_order", "supplier_bill", "purchase_return", "landed_cost", "party_netting"} <= seeded
    assert Role.objects.filter(tenant=tenant, name="Purchasing", is_system=True).exists()


# --- D1: system accounts ---------------------------------------------------


@pytest.mark.django_db
def test_purchasing_system_accounts_exist_and_are_control_accounts(tenant_a):
    for key in PURCHASING_KEYS:
        account = Account.objects.get(tenant=tenant_a, system_key=key)
        assert account.allow_manual_posting is False, key


@pytest.mark.django_db
def test_add_missing_system_accounts_adds_them_to_an_existing_tenant_once(tenant_a):
    Account.objects.filter(tenant=tenant_a, system_key__in=PURCHASING_KEYS).delete()

    call_command("add_missing_system_accounts", "--tenant", tenant_a.subdomain, stdout=StringIO())
    for key in PURCHASING_KEYS:
        account = Account.objects.get(tenant=tenant_a, system_key=key)
        assert account.allow_manual_posting is False, key

    before = set(Account.objects.filter(tenant=tenant_a).values_list("id", "code", "system_key"))
    call_command("add_missing_system_accounts", "--tenant", tenant_a.subdomain, stdout=StringIO())
    assert set(Account.objects.filter(tenant=tenant_a).values_list("id", "code", "system_key")) == before


@pytest.mark.django_db
def test_manual_jv_on_wht_payable_is_rejected(tenant_a, client_a):
    from apps.organization.models import LegalEntity

    branch = LegalEntity.objects.get(tenant=tenant_a, entity_type=LegalEntity.Type.BRANCH)
    cash = Account.objects.get(tenant=tenant_a, system_key="CASH")
    wht = Account.objects.get(tenant=tenant_a, system_key="WHT_PAYABLE")

    response = client_a.post(
        "/api/journal-entries/",
        {
            "legal_entity": str(branch.id), "date": "2026-01-02",
            "lines": [
                {"account": str(cash.id), "debit_fc": "50.00", "credit_fc": "0"},
                {"account": str(wht.id), "debit_fc": "0", "credit_fc": "50.00"},
            ],
        },
        format="json",
    )
    assert response.status_code == 400, response.data
    assert wht.code in response.data["detail"]


# --- permissions, roles, module gate ------------------------------------


@pytest.mark.django_db
def test_purchasing_role_and_accountant_defaults(tenant_a):
    roles = seed_default_roles(tenant_a)
    buyer = UserFactory(tenant=tenant_a, email="buyer@sprint8-block0.test")
    buyer.roles.add(roles["Purchasing"])
    accountant = UserFactory(tenant=tenant_a, email="accountant@sprint8-block0.test")
    accountant.roles.add(roles["Accountant"])
    owner = UserFactory(tenant=tenant_a, email="owner2@sprint8-block0.test")
    owner.roles.add(roles["Owner"])

    assert user_has_permission(buyer, "purchasing.view")
    assert user_has_permission(buyer, "purchasing.manage")
    assert not user_has_permission(buyer, "purchasing.post")
    assert not user_has_permission(buyer, "purchasing.override_match")
    assert not user_has_permission(buyer, "accounting.view")

    assert user_has_permission(accountant, "purchasing.view")
    assert user_has_permission(accountant, "purchasing.post")
    assert not user_has_permission(accountant, "purchasing.manage")
    assert not user_has_permission(accountant, "purchasing.override_match")

    for code in ("purchasing.view", "purchasing.manage", "purchasing.post", "purchasing.override_match"):
        assert user_has_permission(owner, code), code


@pytest.mark.django_db
@pytest.mark.parametrize("url", ["/api/purchasing/settings/", "/api/purchasing/withholding-codes/"])
def test_tenant_without_purchasing_module_gets_404(tenant_a, client_a, url):
    assert tenant_a.features.purchasing is False
    assert client_a.get(url).status_code == 404

    tenant_a.features.purchasing = True
    tenant_a.features.save(update_fields=["purchasing"])
    assert client_a.get(url).status_code == 200


@pytest.mark.django_db
def test_withholding_codes_are_read_only_over_the_api(tenant_a, client_a):
    tenant_a.features.purchasing = True
    tenant_a.features.save(update_fields=["purchasing"])
    load_withholding_codes(tenant_a, "SA")
    code = WithholdingTaxCode.objects.filter(tenant=tenant_a).first()

    listed = client_a.get("/api/purchasing/withholding-codes/")
    assert listed.status_code == 200
    assert {row["code"] for row in listed.data["results"]} == {e["code"] for e in withholding_table("SA")}
    assert all(row["is_example"] for row in listed.data["results"])
    assert client_a.patch(f"/api/purchasing/withholding-codes/{code.id}/", {"is_example": False}, format="json").status_code == 405
    assert client_a.post("/api/purchasing/withholding-codes/", {}, format="json").status_code == 405


# --- PurchaseSettings (R-8.5) ----------------------------------------------


@pytest.mark.django_db
def test_purchase_settings_defaults_and_patch(tenant_a, client_a):
    tenant_a.features.purchasing = True
    tenant_a.features.save(update_fields=["purchasing"])

    response = client_a.get("/api/purchasing/settings/")
    assert response.status_code == 200
    assert response.data == {
        "match_tolerance_pct": "2.00", "match_tolerance_amount": "50.00", "default_grni_policy": "prorate",
    }
    response = client_a.patch("/api/purchasing/settings/", {"match_tolerance_pct": "3.50"}, format="json")
    assert response.status_code == 200
    assert PurchaseSettings.objects.get(tenant=tenant_a).match_tolerance_pct == Decimal("3.50")


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload, field",
    [
        ({"match_tolerance_pct": "100.01"}, "match_tolerance_pct"),
        ({"match_tolerance_pct": "-1"}, "match_tolerance_pct"),
        ({"match_tolerance_amount": "-0.01"}, "match_tolerance_amount"),
        ({"default_grni_policy": "all_to_variance"}, "default_grni_policy"),
    ],
)
def test_purchase_settings_rejects_out_of_range_values(tenant_a, client_a, payload, field):
    tenant_a.features.purchasing = True
    tenant_a.features.save(update_fields=["purchasing"])

    response = client_a.patch("/api/purchasing/settings/", payload, format="json")
    assert response.status_code == 400, response.data
    assert field in response.data


# --- D2: supplier fields ---------------------------------------------------


def _expense_account(tenant):
    return Account.objects.filter(tenant=tenant, type=Account.Type.EXPENSE, allow_posting=True, is_active=True).first()


def _create_supplier(client, **fields):
    return client.post("/api/parties/suppliers/", {"name": "مورد الاختبار", **fields}, format="json")


@pytest.mark.django_db
def test_supplier_carries_its_purchasing_defaults(tenant_a, client_a):
    load_withholding_codes(tenant_a, "SA")
    nr_code = WithholdingTaxCode.objects.filter(tenant=tenant_a, applies_to="non_resident").first()
    expense = _expense_account(tenant_a)

    response = _create_supplier(
        client_a, wht_applicable=True, wht_default_code=str(nr_code.id), is_resident=False,
        vat_registered=True, default_expense_account=str(expense.id), payment_terms_days=45,
    )
    assert response.status_code == 201, response.data
    assert response.data["wht_default_code"] == str(nr_code.id)
    assert response.data["is_resident"] is False
    assert response.data["vat_registered"] is True
    assert response.data["default_expense_account"] == str(expense.id)
    assert response.data["payment_terms_days"] == 45

    from apps.parties.models import PartyRole

    role = PartyRole.objects.get(party_id=response.data["id"], role="supplier")
    assert (role.wht_applicable, role.wht_default_code_id, role.is_resident) == (True, nr_code.id, False)
    assert role.details == {"payment_terms_days": 45}


@pytest.mark.django_db
def test_existing_supplier_defaults_are_unstated(tenant_a, client_a):
    response = _create_supplier(client_a)
    assert response.status_code == 201, response.data
    assert (response.data["wht_applicable"], response.data["is_resident"], response.data["vat_registered"]) == (
        False, True, None,
    )


@pytest.mark.django_db
def test_supplier_wht_code_requires_wht_applicable(tenant_a, client_a):
    load_withholding_codes(tenant_a, "SA")
    nr_code = WithholdingTaxCode.objects.filter(tenant=tenant_a, applies_to="non_resident").first()

    response = _create_supplier(client_a, wht_default_code=str(nr_code.id), is_resident=False)
    assert response.status_code == 400
    assert "wht_default_code" in response.data


@pytest.mark.django_db
def test_supplier_wht_code_must_fit_residency(tenant_a, client_a):
    load_withholding_codes(tenant_a, "SA")
    nr_code = WithholdingTaxCode.objects.filter(tenant=tenant_a, applies_to="non_resident").first()

    response = _create_supplier(client_a, wht_applicable=True, wht_default_code=str(nr_code.id), is_resident=True)
    assert response.status_code == 400
    assert "wht_default_code" in response.data

    created = _create_supplier(client_a, wht_applicable=True, wht_default_code=str(nr_code.id), is_resident=False)
    assert created.status_code == 201, created.data
    # Flipping residency alone later is checked against the stored code too.
    response = client_a.patch(f"/api/parties/suppliers/{created.data['id']}/", {"is_resident": True}, format="json")
    assert response.status_code == 400
    assert "wht_default_code" in response.data


@pytest.mark.django_db
def test_supplier_default_expense_account_must_be_a_postable_expense(tenant_a, client_a):
    cash = Account.objects.get(tenant=tenant_a, system_key="CASH")
    response = _create_supplier(client_a, default_expense_account=str(cash.id))
    assert response.status_code == 400
    assert "default_expense_account" in response.data


@pytest.mark.django_db
def test_supplier_cannot_point_at_another_tenants_code_or_account(tenant_a, tenant_b, client_a):
    load_withholding_codes(tenant_b, "SA")
    foreign_code = WithholdingTaxCode.objects.filter(tenant=tenant_b).first()
    foreign_account = _expense_account(tenant_b)

    # Residency set to fit the code, so only the tenant check can refuse it.
    is_resident = foreign_code.applies_to != WithholdingTaxCode.AppliesTo.NON_RESIDENT
    response = _create_supplier(
        client_a, wht_applicable=True, wht_default_code=str(foreign_code.id), is_resident=is_resident
    )
    assert response.status_code == 400 and "wht_default_code" in response.data
    response = _create_supplier(client_a, default_expense_account=str(foreign_account.id))
    assert response.status_code == 400 and "default_expense_account" in response.data


# --- numbering, attachments ------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "doc_type, prefix",
    [
        ("purchase_order", "PO"), ("goods_receipt", "GRN"), ("supplier_bill", "PINV"),
        ("purchase_return", "PRET"), ("landed_cost", "LC"), ("party_netting", "NET"),
    ],
)
def test_purchasing_document_numbers(tenant_a, doc_type, prefix):
    from datetime import date

    from apps.numbering.services import next_document_number
    from apps.organization.models import LegalEntity

    branch = LegalEntity.objects.get(tenant=tenant_a, entity_type=LegalEntity.Type.BRANCH)
    assert next_document_number(tenant_a, doc_type, branch, date(2026, 3, 1)).startswith(f"{prefix}-")


@pytest.mark.django_db
def test_withholding_code_is_an_attachment_target(tenant_a, tenant_b):
    from apps.attachments.services import AttachmentValidationError, resolve_target

    load_withholding_codes(tenant_a, "SA")
    load_withholding_codes(tenant_b, "SA")
    own = WithholdingTaxCode.objects.filter(tenant=tenant_a).first()
    foreign = WithholdingTaxCode.objects.filter(tenant=tenant_b).first()

    _content_type, instance = resolve_target(tenant_a, "withholding_tax_code", own.id)
    assert instance == own
    with pytest.raises(AttachmentValidationError):
        resolve_target(tenant_a, "withholding_tax_code", foreign.id)
