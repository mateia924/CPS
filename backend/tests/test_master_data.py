"""Sprint 3 (docs/SYSTEM_ANALYSIS.md 3.3, 3.2): unified Party ("طرف")
master data with roles, treasury registration (Bank/CashBox/Custody),
and the fixed-assets registry, plus the CostCenter auto-link that
sprint 1 only laid plumbing for. Covers every explicit test scenario
from the sprint 3 spec section 6.

The Customer -> Party migration itself (backfilling pre-existing rows)
isn't re-exercised here — a fresh test database is built via `migrate`
with an empty sales_customer table, so there's nothing for that data
migration to backfill; it was verified by hand against the real dev
database's data (Acme Trading included) before this sprint's commit —
same documented limitation as the sprint 1 legal_entity backfill (see
README "حدود معروفة في التغطية الآلية").
"""

import pytest

from apps.organization.models import CostCenter
from apps.organization.services import get_or_create_linked_cost_center
from apps.parties.models import Party, PartyRole
from apps.platform.models import Plan
from apps.tenants.services import apply_plan_to_tenant
from apps.treasury.models import Bank

from .factories import (
    AssetFactory,
    LegalEntityFactory,
    PartyFactory,
    PartyRoleFactory,
    ProductFactory,
)

# ---------------------------------------------------------------------
# Party roles: one party, several roles, no duplicates
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_party_can_hold_two_roles_without_duplication(tenant_a, client_a):
    party = PartyFactory(tenant=tenant_a)  # already holds CUSTOMER
    response = client_a.post(f"/api/parties/{party.id}/add-role/", {"role": "supplier"}, format="json")
    assert response.status_code == 201
    assert sorted(r["role"] for r in response.data["roles"]) == ["customer", "supplier"]


@pytest.mark.django_db
def test_adding_a_role_the_party_already_has_returns_400(tenant_a, client_a):
    party = PartyFactory(tenant=tenant_a)
    response = client_a.post(f"/api/parties/{party.id}/add-role/", {"role": "customer"}, format="json")
    assert response.status_code == 400


@pytest.mark.django_db
def test_add_role_on_other_tenant_party_returns_404(tenant_b, client_a):
    party_b = PartyFactory(tenant=tenant_b)
    response = client_a.post(f"/api/parties/{party_b.id}/add-role/", {"role": "supplier"}, format="json")
    assert response.status_code == 404


@pytest.mark.django_db
def test_affiliate_role_requires_a_legal_entity(tenant_a, client_a):
    response = client_a.post("/api/parties/", {"name": "Sibling Co", "role": "affiliate"}, format="json")
    assert response.status_code == 400


@pytest.mark.django_db
def test_affiliate_role_with_legal_entity_succeeds(tenant_a, client_a):
    entity = LegalEntityFactory(tenant=tenant_a)
    response = client_a.post(
        "/api/parties/",
        {"name": "Sibling Co", "role": "affiliate", "role_legal_entity": str(entity.id)},
        format="json",
    )
    assert response.status_code == 201
    assert response.data["roles"][0]["legal_entity"] == entity.id


@pytest.mark.django_db
def test_party_list_filtered_by_role_tab(tenant_a, client_a):
    customer_party = PartyFactory(tenant=tenant_a, name="Cust Co")
    supplier_only = Party.objects.create(tenant=tenant_a, code="P-9002", name="Supplier Co")
    PartyRole.objects.create(party=supplier_only, role=PartyRole.Role.SUPPLIER)

    response = client_a.get("/api/parties/?role=customer")
    names = [p["name"] for p in response.data["results"]]
    assert customer_party.name in names
    assert "Supplier Co" not in names


# ---------------------------------------------------------------------
# Invoicing only accepts a party holding the CUSTOMER role
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_invoice_with_party_lacking_customer_role_returns_400(tenant_a, client_a):
    party = Party.objects.create(tenant=tenant_a, code="P-9001", name="No Role Co")
    product = ProductFactory(tenant=tenant_a)
    response = client_a.post(
        "/api/invoices/",
        {"customer": str(party.id), "lines": [{"product": str(product.id), "quantity": "1"}]},
        format="json",
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------
# Treasury: Bank/CashBox/Custody scoped to the tenant's own legal
# entities; Custody requires the EMPLOYEE role.
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_bank_rejects_other_tenant_legal_entity(tenant_a, tenant_b, client_a):
    other_entity = LegalEntityFactory(tenant=tenant_b)
    response = client_a.post(
        "/api/banks/", {"legal_entity": str(other_entity.id), "name": "Main Account"}, format="json"
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_bank_create_succeeds_with_own_legal_entity(tenant_a, client_a):
    entity = LegalEntityFactory(tenant=tenant_a)
    response = client_a.post(
        "/api/banks/", {"legal_entity": str(entity.id), "name": "Main Account"}, format="json"
    )
    assert response.status_code == 201


@pytest.mark.django_db
def test_custody_requires_employee_role(tenant_a, client_a):
    entity = LegalEntityFactory(tenant=tenant_a)
    non_employee = PartyFactory(tenant=tenant_a)  # CUSTOMER role only
    response = client_a.post(
        "/api/custodies/",
        {"legal_entity": str(entity.id), "employee": str(non_employee.id), "name": "Custody 1"},
        format="json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_custody_succeeds_with_employee_role(tenant_a, client_a):
    entity = LegalEntityFactory(tenant=tenant_a)
    employee = PartyFactory(tenant=tenant_a)
    PartyRoleFactory(party=employee, role=PartyRole.Role.EMPLOYEE)
    response = client_a.post(
        "/api/custodies/",
        {"legal_entity": str(entity.id), "employee": str(employee.id), "name": "Custody 1"},
        format="json",
    )
    assert response.status_code == 201


# ---------------------------------------------------------------------
# CostCenter auto-link: on by default for VEHICLE assets, opt-in for
# EMPLOYEE roles, and never created twice for the same linked object.
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_vehicle_asset_auto_creates_linked_cost_center(tenant_a, client_a):
    entity = LegalEntityFactory(tenant=tenant_a)
    response = client_a.post(
        "/api/assets/",
        {
            "legal_entity": str(entity.id),
            "code": "AST-0001",
            "name": "Delivery Van",
            "category": "vehicle",
            "purchase_date": "2026-01-01",
            "purchase_cost": "80000.00",
        },
        format="json",
    )
    assert response.status_code == 201
    assert response.data["cost_center"] is not None
    assert CostCenter.objects.filter(
        tenant=tenant_a, name="Delivery Van", center_type=CostCenter.Type.VEHICLE
    ).exists()


@pytest.mark.django_db
def test_non_vehicle_asset_does_not_create_linked_cost_center(tenant_a, client_a):
    entity = LegalEntityFactory(tenant=tenant_a)
    response = client_a.post(
        "/api/assets/",
        {
            "legal_entity": str(entity.id),
            "code": "AST-0002",
            "name": "Office Laptop",
            "category": "it",
            "purchase_date": "2026-01-01",
            "purchase_cost": "5000.00",
        },
        format="json",
    )
    assert response.status_code == 201
    assert response.data["cost_center"] is None


@pytest.mark.django_db
def test_get_or_create_linked_cost_center_is_idempotent(tenant_a):
    asset = AssetFactory(tenant=tenant_a, category="vehicle", code="AST-0777", name="Truck")
    first = get_or_create_linked_cost_center(
        tenant=tenant_a, linked_object=asset, code=f"CC-{asset.code}",
        name=asset.name, center_type=CostCenter.Type.VEHICLE,
    )
    second = get_or_create_linked_cost_center(
        tenant=tenant_a, linked_object=asset, code=f"CC-{asset.code}",
        name=asset.name, center_type=CostCenter.Type.VEHICLE,
    )
    assert first.id == second.id
    assert CostCenter.objects.filter(tenant=tenant_a, name="Truck").count() == 1


@pytest.mark.django_db
def test_employee_role_linked_cost_center_is_opt_in_and_off_by_default(tenant_a, client_a):
    response = client_a.post(
        "/api/parties/", {"name": "Employee One", "role": "employee"}, format="json"
    )
    assert response.status_code == 201
    assert not CostCenter.objects.filter(tenant=tenant_a, name="Employee One").exists()


@pytest.mark.django_db
def test_employee_role_linked_cost_center_created_when_requested(tenant_a, client_a):
    response = client_a.post(
        "/api/parties/",
        {"name": "Employee Two", "role": "employee", "role_create_linked_cost_center": True},
        format="json",
    )
    assert response.status_code == 201
    assert CostCenter.objects.filter(
        tenant=tenant_a, name="Employee Two", center_type=CostCenter.Type.EMPLOYEE
    ).exists()


# ---------------------------------------------------------------------
# Tenant isolation on every new model (list/404/create)
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_party_list_excludes_other_tenant(tenant_a, tenant_b, client_a):
    PartyFactory(tenant=tenant_b, name="B Party")
    response = client_a.get("/api/parties/")
    names = [p["name"] for p in response.data["results"]]
    assert "B Party" not in names


@pytest.mark.django_db
def test_get_other_tenant_party_returns_404(tenant_b, client_a):
    party_b = PartyFactory(tenant=tenant_b)
    response = client_a.get(f"/api/parties/{party_b.id}/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_bank_list_excludes_other_tenant(tenant_a, tenant_b, client_a):
    entity_b = LegalEntityFactory(tenant=tenant_b)
    Bank.objects.create(tenant=tenant_b, legal_entity=entity_b, name="B Bank")
    response = client_a.get("/api/banks/")
    names = [b["name"] for b in response.data["results"]]
    assert "B Bank" not in names


@pytest.mark.django_db
def test_get_other_tenant_bank_returns_404(tenant_a, tenant_b, client_a):
    entity_b = LegalEntityFactory(tenant=tenant_b)
    bank_b = Bank.objects.create(tenant=tenant_b, legal_entity=entity_b, name="B Bank")
    response = client_a.get(f"/api/banks/{bank_b.id}/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_asset_list_excludes_other_tenant(tenant_a, tenant_b, client_a):
    AssetFactory(tenant=tenant_b, code="AST-B01", name="B Asset")
    response = client_a.get("/api/assets/")
    names = [a["name"] for a in response.data["results"]]
    assert "B Asset" not in names


@pytest.mark.django_db
def test_get_other_tenant_asset_returns_404(tenant_a, tenant_b, client_a):
    asset_b = AssetFactory(tenant=tenant_b, code="AST-B02")
    response = client_a.get(f"/api/assets/{asset_b.id}/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_create_asset_with_other_tenant_legal_entity_rejected(tenant_a, tenant_b, client_a):
    other_entity = LegalEntityFactory(tenant=tenant_b)
    response = client_a.post(
        "/api/assets/",
        {
            "legal_entity": str(other_entity.id),
            "code": "AST-0099",
            "name": "Cross-tenant Asset",
            "category": "equipment",
            "purchase_date": "2026-01-01",
            "purchase_cost": "1000.00",
        },
        format="json",
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------
# treasury/assets feature flags follow the plan (3.13/3.3): Free hides
# them, Business+ shows them — same mechanism as every other flag.
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_free_plan_hides_treasury_and_assets(client_a, tenant_a):
    apply_plan_to_tenant(tenant_a, Plan.objects.get(code="free"))
    response = client_a.get("/api/auth/me/")
    assert response.data["features"]["treasury"] is False
    assert response.data["features"]["assets"] is False


@pytest.mark.django_db
def test_business_plan_shows_treasury_and_assets(client_a, tenant_a):
    apply_plan_to_tenant(tenant_a, Plan.objects.get(code="business"))
    response = client_a.get("/api/auth/me/")
    assert response.data["features"]["treasury"] is True
    assert response.data["features"]["assets"] is True


@pytest.mark.django_db
def test_free_plan_owner_still_has_accounting_reports_settings_permissions(client_a, tenant_a):
    """Sprint 4.8 regression guard (3.18): "المحاسبة"/"التقارير" always
    show and "الإعدادات" shows per-permission — none of the three are
    plan/feature-gated, unlike purchasing/treasury/assets. The
    frontend sidebar (dashboard/layout.tsx) gates them purely on
    `me.permissions`, so this asserts the actual contract at its
    source: an Owner on the Free plan (every `features.*` flag False)
    must still carry accounting.view/approvals.view/numbering.view/
    roles.manage — the permission codes those sidebar sections check.
    """
    apply_plan_to_tenant(tenant_a, Plan.objects.get(code="free"))
    response = client_a.get("/api/auth/me/")
    assert all(value is False for value in response.data["features"].values())
    permissions = response.data["permissions"]
    assert "accounting.view" in permissions
    assert "approvals.view" in permissions
    assert "numbering.view" in permissions
    assert "roles.manage" in permissions
