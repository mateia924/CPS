"""docs/SYSTEM_ANALYSIS.md 3.1: unlimited-depth legal entity tree, with
two hard rules — a BRANCH can never have children, and the tree can
never contain a cycle. Also covers the /tree endpoint's nesting shape.
"""

import pytest
from rest_framework.test import APIClient

from apps.access.services import seed_default_roles
from apps.organization.models import LegalEntity

from .factories import TenantFactory, UserFactory


@pytest.fixture
def owner_client(db):
    tenant = TenantFactory(subdomain="org-tree-tenant")
    user = UserFactory(tenant=tenant, email="owner@org-tree.test")
    roles = seed_default_roles(tenant)
    user.roles.add(roles["Owner"])
    client = APIClient()
    client.force_authenticate(user=user)
    return client, tenant


@pytest.mark.django_db
def test_branch_cannot_have_children(owner_client):
    client, tenant = owner_client
    company = LegalEntity.objects.create(
        tenant=tenant, code="C1", name="Co", entity_type=LegalEntity.Type.COMPANY
    )
    branch = LegalEntity.objects.create(
        tenant=tenant, code="B1", name="Branch", entity_type=LegalEntity.Type.BRANCH, parent=company
    )

    response = client.post(
        "/api/legal-entities/",
        {"code": "B1-SUB", "name": "Sub", "entity_type": "branch", "parent": str(branch.id)},
        format="json",
    )
    assert response.status_code == 400
    assert "parent" in response.data


@pytest.mark.django_db
def test_cycle_prevented_on_update(owner_client):
    client, tenant = owner_client
    root = LegalEntity.objects.create(
        tenant=tenant, code="R", name="Root", entity_type=LegalEntity.Type.HOLDING
    )
    child = LegalEntity.objects.create(
        tenant=tenant, code="C", name="Child", entity_type=LegalEntity.Type.COMPANY, parent=root
    )

    # Making root a child of its own child would create a cycle.
    response = client.patch(
        f"/api/legal-entities/{root.id}/", {"parent": str(child.id)}, format="json"
    )
    assert response.status_code == 400
    assert "parent" in response.data


@pytest.mark.django_db
def test_entity_cannot_be_its_own_parent(owner_client):
    client, tenant = owner_client
    entity = LegalEntity.objects.create(
        tenant=tenant, code="SELF", name="Self", entity_type=LegalEntity.Type.HOLDING
    )
    response = client.patch(
        f"/api/legal-entities/{entity.id}/", {"parent": str(entity.id)}, format="json"
    )
    assert response.status_code == 400
    assert "parent" in response.data


@pytest.mark.django_db
def test_tree_endpoint_returns_correct_nesting_depth_4(owner_client):
    client, tenant = owner_client
    l1 = LegalEntity.objects.create(
        tenant=tenant, code="L1", name="Holding", entity_type=LegalEntity.Type.HOLDING
    )
    l2 = LegalEntity.objects.create(
        tenant=tenant, code="L2", name="Sub Holding Co", entity_type=LegalEntity.Type.COMPANY, parent=l1
    )
    l3 = LegalEntity.objects.create(
        tenant=tenant, code="L3", name="Regional Co", entity_type=LegalEntity.Type.COMPANY, parent=l2
    )
    LegalEntity.objects.create(
        tenant=tenant, code="L4", name="Branch", entity_type=LegalEntity.Type.BRANCH, parent=l3
    )

    response = client.get("/api/legal-entities/tree/")
    assert response.status_code == 200
    assert len(response.data) == 1

    root = response.data[0]
    assert root["code"] == "L1"
    assert len(root["children"]) == 1
    assert root["children"][0]["code"] == "L2"
    assert root["children"][0]["children"][0]["code"] == "L3"
    assert root["children"][0]["children"][0]["children"][0]["code"] == "L4"
    assert root["children"][0]["children"][0]["children"][0]["children"] == []


# ---------------------------------------------------------------------
# Sprint 5.6 (block 5.6): شاشة "الشركة" — structured address + CR +
# Saudi tax-number format validation + field-by-field inheritance from
# the parent entity.
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_saudi_tax_number_format_validated(owner_client):
    client, tenant = owner_client
    entity = LegalEntity.objects.create(
        tenant=tenant, code="C1", name="Co", entity_type=LegalEntity.Type.COMPANY
    )

    bad = client.patch(f"/api/legal-entities/{entity.id}/", {"tax_number": "12345"}, format="json")
    assert bad.status_code == 400, bad.data

    bad_edges = client.patch(f"/api/legal-entities/{entity.id}/", {"tax_number": "1" * 15}, format="json")
    assert bad_edges.status_code == 400, bad_edges.data

    good = client.patch(
        f"/api/legal-entities/{entity.id}/", {"tax_number": "3" + "1" * 13 + "3"}, format="json"
    )
    assert good.status_code == 200, good.data
    assert good.data["tax_number"] == "3" + "1" * 13 + "3"


@pytest.mark.django_db
def test_commercial_registration_format_validated(owner_client):
    client, tenant = owner_client
    entity = LegalEntity.objects.create(
        tenant=tenant, code="C1", name="Co", entity_type=LegalEntity.Type.COMPANY
    )

    bad = client.patch(f"/api/legal-entities/{entity.id}/", {"commercial_registration": "123"}, format="json")
    assert bad.status_code == 400, bad.data

    good = client.patch(
        f"/api/legal-entities/{entity.id}/", {"commercial_registration": "1010101010"}, format="json"
    )
    assert good.status_code == 200, good.data


@pytest.mark.django_db
def test_branch_inherits_blank_company_profile_fields_from_parent(owner_client):
    client, tenant = owner_client
    company = LegalEntity.objects.create(
        tenant=tenant, code="C1", name="Co", entity_type=LegalEntity.Type.COMPANY,
        commercial_registration="1010101010", city="Riyadh", phone="0112345678",
    )
    branch = LegalEntity.objects.create(
        tenant=tenant, code="B1", name="Branch", entity_type=LegalEntity.Type.BRANCH, parent=company,
        city="Jeddah",
    )

    response = client.get(f"/api/legal-entities/{branch.id}/")
    assert response.status_code == 200
    profile = response.data["effective_profile"]
    # own value wins where set...
    assert profile["city"] == "Jeddah"
    # ...blank fields fall back to the parent's.
    assert profile["commercial_registration"] == "1010101010"
    assert profile["phone"] == "0112345678"
