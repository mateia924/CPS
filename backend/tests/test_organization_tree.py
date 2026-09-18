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
