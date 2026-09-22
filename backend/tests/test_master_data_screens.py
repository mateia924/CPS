"""Sprint 3.5 (docs/SYSTEM_ANALYSIS.md 3.3 v1.4): separate accountant-
facing screens for master data, after UAT rejected the unified "طرف
بدور" screen from sprint 3. Each screen (Customers/Suppliers/Employees/
Affiliates) is a role-fixed view onto the same Party/PartyRole tables —
no `role` field ever accepted from the client, and a backend
check-duplicate endpoint backs the "already registered as X — add as Y
too?" confirmation flow instead of a silent frontend guess.
"""

import pytest

from apps.organization.models import LegalEntity
from apps.parties.models import Party, PartyRole

from .factories import LegalEntityFactory, PartyFactory

# ---------------------------------------------------------------------
# Dedicated create endpoints: role is fixed server-side, never accepted
# from the client.
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_creating_a_customer_auto_creates_customer_role(tenant_a, client_a):
    response = client_a.post("/api/parties/customers/", {"name": "Nile Retail"}, format="json")
    assert response.status_code == 201
    assert [r["role"] for r in response.data["roles"]] == ["customer"]


@pytest.mark.django_db
def test_creating_a_customer_rejects_roles_field(tenant_a, client_a):
    response = client_a.post(
        "/api/parties/customers/",
        {"name": "Bad Co", "roles": [{"role": "supplier"}]},
        format="json",
    )
    assert response.status_code == 400
    assert "roles" in response.data


@pytest.mark.django_db
def test_creating_a_customer_rejects_role_field(tenant_a, client_a):
    response = client_a.post(
        "/api/parties/customers/", {"name": "Bad Co", "role": "supplier"}, format="json"
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_customer_screen_accepts_role_specific_fields(tenant_a, client_a):
    response = client_a.post(
        "/api/parties/customers/",
        {"name": "Nile Retail", "credit_limit": "5000.00", "payment_terms_days": 30},
        format="json",
    )
    assert response.status_code == 201
    assert response.data["credit_limit"] == "5000.00"
    assert response.data["payment_terms_days"] == 30  # stays an int, not stringified


@pytest.mark.django_db
def test_creating_an_affiliate_requires_legal_entity(tenant_a, client_a):
    response = client_a.post("/api/parties/affiliates/", {"name": "Sister Co"}, format="json")
    assert response.status_code == 400
    assert "legal_entity" in response.data


@pytest.mark.django_db
def test_creating_an_affiliate_with_legal_entity_succeeds(tenant_a, client_a):
    entity = LegalEntityFactory(tenant=tenant_a, entity_type=LegalEntity.Type.COMPANY)
    response = client_a.post(
        "/api/parties/affiliates/", {"name": "Sister Co", "legal_entity": str(entity.id)}, format="json"
    )
    assert response.status_code == 201
    assert response.data["legal_entity"] == entity.id


@pytest.mark.django_db
def test_creating_an_employee_with_linked_cost_center(tenant_a, client_a):
    from apps.organization.models import CostCenter

    entity = LegalEntityFactory(tenant=tenant_a, entity_type=LegalEntity.Type.BRANCH)
    response = client_a.post(
        "/api/parties/employees/",
        {"name": "Ahmed Ali", "job_title": "Accountant", "branch": str(entity.id), "create_linked_cost_center": True},
        format="json",
    )
    assert response.status_code == 201
    assert response.data["branch"] == entity.id
    assert CostCenter.objects.filter(
        tenant=tenant_a, name="Ahmed Ali", center_type=CostCenter.Type.EMPLOYEE
    ).exists()


@pytest.mark.django_db
def test_creating_an_employee_without_requesting_cost_center_does_not_create_one(tenant_a, client_a):
    from apps.organization.models import CostCenter

    response = client_a.post("/api/parties/employees/", {"name": "Sara Omar"}, format="json")
    assert response.status_code == 201
    assert not CostCenter.objects.filter(tenant=tenant_a, name="Sara Omar").exists()


# ---------------------------------------------------------------------
# Duplicate detection: check-duplicate + add-role linking, no new Party
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_check_duplicate_finds_existing_party_by_tax_number(tenant_a, client_a):
    client_a.post(
        "/api/parties/customers/",
        {"name": "Nile Retail", "tax_number": "300123456700003"},
        format="json",
    )
    response = client_a.get("/api/parties/check-duplicate/?tax_number=300123456700003")
    assert response.status_code == 200
    assert response.data["party"] is not None
    assert response.data["party"]["name"] == "Nile Retail"
    assert [r["role"] for r in response.data["party"]["roles"]] == ["customer"]


@pytest.mark.django_db
def test_check_duplicate_returns_null_when_no_match(tenant_a, client_a):
    response = client_a.get("/api/parties/check-duplicate/?tax_number=999999999")
    assert response.status_code == 200
    assert response.data["party"] is None


@pytest.mark.django_db
def test_confirming_duplicate_links_role_without_creating_new_party(tenant_a, client_a):
    created = client_a.post(
        "/api/parties/customers/",
        {"name": "Nile Retail", "tax_number": "300123456700003"},
        format="json",
    )
    party_id = created.data["id"]
    count_before = Party.objects.filter(tenant=tenant_a).count()

    response = client_a.post(f"/api/parties/{party_id}/add-role/", {"role": "supplier"}, format="json")
    assert response.status_code == 201

    assert Party.objects.filter(tenant=tenant_a).count() == count_before


@pytest.mark.django_db
def test_party_appears_in_both_customer_and_supplier_lists_after_second_role(tenant_a, client_a):
    created = client_a.post("/api/parties/customers/", {"name": "Nile Retail"}, format="json")
    party_id = created.data["id"]
    client_a.post(f"/api/parties/{party_id}/add-role/", {"role": "supplier"}, format="json")

    customers = client_a.get("/api/parties/customers/")
    suppliers = client_a.get("/api/parties/suppliers/")
    assert "Nile Retail" in [p["name"] for p in customers.data["results"]]
    assert "Nile Retail" in [p["name"] for p in suppliers.data["results"]]


# ---------------------------------------------------------------------
# The unified "الأطراف (عرض شامل)" screen: view_all-gated
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_full_parties_view_requires_view_all_permission(tenant_a, user_a, client_a):
    from apps.access.models import Permission, Role

    # Swap the Owner-only fixture user to a bare custom role with
    # parties.manage but not parties.view_all, matching how a
    # non-accounts-manager staff member would be configured.
    limited_role = Role.objects.create(tenant=tenant_a, name="Limited", is_system=False)
    limited_role.permissions.set(Permission.objects.filter(code__in=["parties.view", "parties.manage"]))
    user_a.roles.set([limited_role])

    response = client_a.get("/api/parties/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_owner_can_reach_full_parties_view(tenant_a, client_a):
    response = client_a.get("/api/parties/")
    assert response.status_code == 200


# ---------------------------------------------------------------------
# Tenant isolation on every new endpoint (list / 404 / create)
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_customer_list_excludes_other_tenant(tenant_a, tenant_b, client_a):
    PartyFactory(tenant=tenant_b, name="B Customer")
    response = client_a.get("/api/parties/customers/")
    names = [p["name"] for p in response.data["results"]]
    assert "B Customer" not in names


@pytest.mark.django_db
def test_get_other_tenant_customer_returns_404(tenant_b, client_a):
    party_b = PartyFactory(tenant=tenant_b)
    response = client_a.get(f"/api/parties/customers/{party_b.id}/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_add_role_on_other_tenant_customer_returns_404(tenant_b, client_a):
    party_b = PartyFactory(tenant=tenant_b)
    response = client_a.post(f"/api/parties/{party_b.id}/add-role/", {"role": "supplier"}, format="json")
    assert response.status_code == 404


@pytest.mark.django_db
def test_check_duplicate_never_finds_another_tenants_party(tenant_a, tenant_b, client_a):
    PartyFactory(tenant=tenant_b, tax_number="300123456700003")
    response = client_a.get("/api/parties/check-duplicate/?tax_number=300123456700003")
    assert response.status_code == 200
    assert response.data["party"] is None


@pytest.mark.django_db
def test_supplier_employee_affiliate_list_all_exclude_other_tenant(tenant_a, tenant_b, client_a):
    other_party = PartyFactory(tenant=tenant_b, name="B Party")
    PartyRole.objects.filter(party=other_party).delete()
    PartyRole.objects.create(party=other_party, role=PartyRole.Role.SUPPLIER)

    response = client_a.get("/api/parties/suppliers/")
    assert response.status_code == 200
    assert "B Party" not in [p["name"] for p in response.data["results"]]
