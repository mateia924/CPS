"""Sprint 4.3 (docs/SYSTEM_ANALYSIS.md 3.4; ARCH_REVIEW_1.md §3.1):
hierarchical chart of accounts, activity templates, auto sub-ledger
accounts."""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from rest_framework.test import APIClient

from apps.accounting.models import Account, JournalEntry, JournalLine
from apps.accounting.services import (
    build_journal_lines_with_fx_rounding,
    get_or_create_party_role_account,
    get_or_create_treasury_account,
    seed_chart_of_accounts,
)
from apps.parties.models import PartyRole
from apps.tenants.models import Tenant
from apps.treasury.models import Bank

from .factories import LegalEntityFactory, PartyFactory, TenantFactory

# ---------------------------------------------------------------------
# Activity templates
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_trading_template_creates_the_full_tree_with_expected_system_keys(db):
    tenant = TenantFactory(business_type=Tenant.BusinessType.TRADING)
    seed_chart_of_accounts(tenant)

    accounts = Account.objects.filter(tenant=tenant)
    assert accounts.count() > 15
    system_keys = set(accounts.exclude(system_key="").values_list("system_key", flat=True))
    assert {"CASH", "BANKS", "CUSTOMERS", "SUPPLIERS", "EMPLOYEES", "CUSTODIES",
            "AFFILIATES", "SALES", "COGS", "VAT_OUTPUT", "VAT_INPUT",
            "VAT_NON_DEDUCTIBLE", "ROUNDING"} <= system_keys

    root = accounts.get(code="1000")
    assert root.level == 0
    assert root.is_leaf is False
    customers = accounts.get(system_key="CUSTOMERS")
    assert customers.level == 1
    assert customers.parent_id == root.id


@pytest.mark.django_db
def test_service_template_is_the_default_and_smaller_than_trading(db):
    tenant = TenantFactory()  # default business_type = service
    seed_chart_of_accounts(tenant)
    service_count = Account.objects.filter(tenant=tenant).count()

    tenant_trading = TenantFactory(business_type=Tenant.BusinessType.TRADING)
    seed_chart_of_accounts(tenant_trading)
    trading_count = Account.objects.filter(tenant=tenant_trading).count()

    assert service_count < trading_count
    assert not Account.objects.filter(tenant=tenant, system_key="COGS").exists()


@pytest.mark.django_db
def test_registration_business_type_selects_the_template():
    client = APIClient()
    response = client.post(
        "/api/auth/register/",
        {
            "company_name": "Trading Co",
            "subdomain": "chart-trading-reg",
            "email": "owner@chart-trading-reg.test",
            "password": "S3curePass!2026",
            "business_type": "trading",
        },
        format="json",
    )
    assert response.status_code == 201
    tenant = Tenant.objects.get(subdomain="chart-trading-reg")
    assert tenant.business_type == "trading"
    assert Account.objects.filter(tenant=tenant, system_key="COGS").exists()


# ---------------------------------------------------------------------
# Posting rules
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_posting_to_a_parent_account_is_rejected(db):
    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    entity = LegalEntityFactory(tenant=tenant)
    parent_account = Account.objects.get(tenant=tenant, code="1000")  # has children -> not a leaf
    entry = JournalEntry.objects.create(tenant=tenant, legal_entity=entity, date="2026-01-01")

    with pytest.raises(ValidationError):
        build_journal_lines_with_fx_rounding(
            tenant, entry,
            [{"account": parent_account, "debit_fc": Decimal("10.00"), "credit_fc": Decimal("0")}],
            Decimal("1"),
        )


@pytest.mark.django_db
def test_posting_to_a_leaf_with_allow_posting_false_is_rejected(db):
    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    entity = LegalEntityFactory(tenant=tenant)
    leaf = Account.objects.get(tenant=tenant, system_key="SALES")
    leaf.allow_posting = False
    leaf.save(update_fields=["allow_posting"])
    entry = JournalEntry.objects.create(tenant=tenant, legal_entity=entity, date="2026-01-01")

    with pytest.raises(ValidationError):
        build_journal_lines_with_fx_rounding(
            tenant, entry,
            [{"account": leaf, "debit_fc": Decimal("10.00"), "credit_fc": Decimal("0")}],
            Decimal("1"),
        )


# ---------------------------------------------------------------------
# Account.clean(): cycles, parent/child type match
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_account_parent_and_child_must_share_the_same_type(db):
    tenant = TenantFactory()
    asset_root = Account.objects.create(tenant=tenant, code="1", name="Assets", type=Account.Type.ASSET)
    liability_child = Account(
        tenant=tenant, code="2", name="Bad Child", type=Account.Type.LIABILITY, parent=asset_root
    )
    with pytest.raises(ValidationError):
        liability_child.clean()


@pytest.mark.django_db
def test_account_cannot_be_its_own_ancestor(db):
    tenant = TenantFactory()
    a = Account.objects.create(tenant=tenant, code="1", name="A", type=Account.Type.ASSET)
    b = Account.objects.create(tenant=tenant, code="2", name="B", type=Account.Type.ASSET, parent=a)
    a.parent = b
    with pytest.raises(ValidationError):
        a.clean()


@pytest.mark.django_db
def test_normal_balance_defaults_from_type_when_not_given(db):
    tenant = TenantFactory()
    asset = Account.objects.create(tenant=tenant, code="1", name="A", type=Account.Type.ASSET)
    liability = Account.objects.create(tenant=tenant, code="2", name="B", type=Account.Type.LIABILITY)
    assert asset.normal_balance == Account.NormalBalance.DEBIT
    assert liability.normal_balance == Account.NormalBalance.CREDIT


# ---------------------------------------------------------------------
# Auto sub-ledger accounts for parties
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_creating_a_customer_generates_its_account_under_customers_once(tenant_a, client_a):
    response = client_a.post(
        "/api/parties/customers/", {"name": "Acme Client"}, format="json"
    )
    assert response.status_code == 201
    from apps.parties.models import Party

    party = Party.objects.get(id=response.data["id"])
    customers_parent = Account.objects.get(tenant=tenant_a, system_key="CUSTOMERS")
    accounts = Account.objects.filter(tenant=tenant_a, party=party, parent=customers_parent)
    assert accounts.count() == 1
    assert customers_parent.is_leaf is False


@pytest.mark.django_db
def test_get_or_create_party_role_account_is_idempotent(db):
    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    party = PartyFactory(tenant=tenant)

    first = get_or_create_party_role_account(party, PartyRole.Role.CUSTOMER)
    second = get_or_create_party_role_account(party, PartyRole.Role.CUSTOMER)

    assert first.id == second.id
    assert Account.objects.filter(tenant=tenant, party=party).count() == 1


@pytest.mark.django_db
def test_party_with_two_roles_gets_two_separate_accounts(tenant_a, client_a):
    create = client_a.post("/api/parties/customers/", {"name": "Dual Role Co"}, format="json")
    assert create.status_code == 201
    party_id = create.data["id"]

    add_role = client_a.post(f"/api/parties/{party_id}/add-role/", {"role": "supplier"}, format="json")
    assert add_role.status_code == 201


    accounts = Account.objects.filter(tenant=tenant_a, party_id=party_id)
    assert accounts.count() == 2
    system_keys = set(accounts.values_list("parent__system_key", flat=True))
    assert system_keys == {"CUSTOMERS", "SUPPLIERS"}


@pytest.mark.django_db
def test_get_or_create_party_role_account_returns_none_without_a_matching_parent(db):
    tenant = TenantFactory()
    # No chart seeded at all -> no CUSTOMERS system_key exists.
    party = PartyFactory(tenant=tenant)
    assert get_or_create_party_role_account(party, PartyRole.Role.CUSTOMER) is None


# ---------------------------------------------------------------------
# Auto accounts for banks/cash boxes/custodies (ARCH_REVIEW_1.md debt #20)
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_creating_a_bank_auto_fills_its_gl_account(tenant_a, client_a):
    entity = LegalEntityFactory(tenant=tenant_a)
    response = client_a.post(
        "/api/banks/", {"legal_entity": str(entity.id), "name": "Main Bank Account"}, format="json"
    )
    assert response.status_code == 201
    bank = Bank.objects.get(id=response.data["id"])
    assert bank.gl_account_id is not None
    assert bank.gl_account.parent.system_key == "BANKS"


@pytest.mark.django_db
def test_get_or_create_treasury_account_is_idempotent(db):
    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    entity = LegalEntityFactory(tenant=tenant)
    bank = Bank.objects.create(tenant=tenant, legal_entity=entity, name="Bank X")

    first = get_or_create_treasury_account(bank, "BANKS")
    bank.refresh_from_db()
    second = get_or_create_treasury_account(bank, "BANKS")

    assert first.id == second.id
    assert Account.objects.filter(tenant=tenant, parent__system_key="BANKS").count() == 1


# ---------------------------------------------------------------------
# 3.15.9: delete/type/parent protection on accounts with posted lines
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_deleting_an_account_with_a_journal_line_returns_409(tenant_a, client_a):
    entity = LegalEntityFactory(tenant=tenant_a)
    account = Account.objects.create(
        tenant=tenant_a, code="9999", name="Test Leaf", type=Account.Type.ASSET
    )
    entry = JournalEntry.objects.create(tenant=tenant_a, legal_entity=entity, date="2026-01-01")
    JournalLine.objects.create(entry=entry, account=account, debit=Decimal("10.00"), debit_fc=Decimal("10.00"))

    response = client_a.delete(f"/api/accounts/{account.id}/")
    assert response.status_code == 409


@pytest.mark.django_db
def test_changing_type_of_an_account_with_posted_lines_returns_400(tenant_a, client_a):
    entity = LegalEntityFactory(tenant=tenant_a)
    account = Account.objects.create(
        tenant=tenant_a, code="9998", name="Test Leaf 2", type=Account.Type.ASSET
    )
    entry = JournalEntry.objects.create(tenant=tenant_a, legal_entity=entity, date="2026-01-01")
    JournalLine.objects.create(entry=entry, account=account, debit=Decimal("10.00"), debit_fc=Decimal("10.00"))

    response = client_a.patch(
        f"/api/accounts/{account.id}/", {"type": "liability"}, format="json"
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_account_without_lines_can_have_its_type_changed(tenant_a, client_a):
    account = Account.objects.create(
        tenant=tenant_a, code="9997", name="Test Leaf 3", type=Account.Type.ASSET
    )
    response = client_a.patch(
        f"/api/accounts/{account.id}/", {"type": "expense"}, format="json"
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------
# دليل الحسابات screen: permissions, tenant isolation, tree
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_viewer_cannot_create_accounts(db):
    from apps.access.services import seed_default_roles

    from .factories import UserFactory

    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    roles = seed_default_roles(tenant)
    viewer = UserFactory(tenant=tenant, email="viewer@coa-perm.test")
    viewer.roles.add(roles["Viewer"])
    client = APIClient()
    client.force_authenticate(user=viewer)

    response = client.post(
        "/api/accounts/", {"code": "9990", "name": "x", "type": "asset"}, format="json"
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_account_tree_action_returns_nested_structure(tenant_a, client_a):
    response = client_a.get("/api/accounts/tree/")
    assert response.status_code == 200
    roots = response.data
    assert any(r["code"] == "1000" and r["children"] for r in roots)


@pytest.mark.django_db
def test_accounts_are_tenant_isolated(tenant_a, tenant_b, client_a):
    other_account = Account.objects.get(tenant=tenant_b, code="1000")
    response = client_a.get(f"/api/accounts/{other_account.id}/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_duplicate_account_code_per_tenant_is_rejected_at_db_level(db):
    tenant = TenantFactory()
    Account.objects.create(tenant=tenant, code="7000", name="A", type=Account.Type.ASSET)
    with pytest.raises(IntegrityError):
        Account.objects.create(tenant=tenant, code="7000", name="B", type=Account.Type.ASSET)
