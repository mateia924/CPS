"""Sprint 1.5 rule 3: a tenant must always keep at least one active
Owner. Also covers the related "can't delete a role/user record that's
still in use" protections on the roles & users screen.
"""

import pytest
from rest_framework.test import APIClient

from apps.access.services import seed_default_roles

from .factories import RoleFactory, TenantFactory, UserFactory


@pytest.fixture
def tenant_with_roles(db):
    tenant = TenantFactory(subdomain="owner-protect")
    roles = seed_default_roles(tenant)
    return tenant, roles


@pytest.mark.django_db
def test_last_active_owner_cannot_be_deactivated(tenant_with_roles):
    tenant, roles = tenant_with_roles
    owner = UserFactory(tenant=tenant, email="only-owner@test.test")
    owner.roles.add(roles["Owner"])
    client = APIClient()
    client.force_authenticate(user=owner)

    response = client.post(f"/api/users/{owner.id}/deactivate/")
    assert response.status_code == 400
    owner.refresh_from_db()
    assert owner.is_active is True


@pytest.mark.django_db
def test_last_active_owner_role_cannot_be_stripped(tenant_with_roles):
    tenant, roles = tenant_with_roles
    owner = UserFactory(tenant=tenant, email="only-owner2@test.test")
    owner.roles.add(roles["Owner"])
    client = APIClient()
    client.force_authenticate(user=owner)

    response = client.post(f"/api/users/{owner.id}/assign/", {"role_ids": []}, format="json")
    assert response.status_code == 400
    assert list(owner.roles.values_list("name", flat=True)) == ["Owner"]


@pytest.mark.django_db
def test_second_owner_can_be_deactivated_when_another_remains(tenant_with_roles):
    tenant, roles = tenant_with_roles
    owner_1 = UserFactory(tenant=tenant, email="owner1@test.test")
    owner_1.roles.add(roles["Owner"])
    owner_2 = UserFactory(tenant=tenant, email="owner2@test.test")
    owner_2.roles.add(roles["Owner"])

    client = APIClient()
    client.force_authenticate(user=owner_1)

    response = client.post(f"/api/users/{owner_2.id}/deactivate/")
    assert response.status_code == 200
    owner_2.refresh_from_db()
    assert owner_2.is_active is False


@pytest.mark.django_db
def test_deactivated_owner_can_be_reactivated(tenant_with_roles):
    tenant, roles = tenant_with_roles
    owner_1 = UserFactory(tenant=tenant, email="owner1b@test.test")
    owner_1.roles.add(roles["Owner"])
    owner_2 = UserFactory(tenant=tenant, email="owner2b@test.test", is_active=False)
    owner_2.roles.add(roles["Owner"])

    client = APIClient()
    client.force_authenticate(user=owner_1)

    response = client.post(f"/api/users/{owner_2.id}/activate/")
    assert response.status_code == 200
    owner_2.refresh_from_db()
    assert owner_2.is_active is True


@pytest.mark.django_db
def test_system_role_cannot_be_deleted(tenant_with_roles):
    tenant, roles = tenant_with_roles
    owner = UserFactory(tenant=tenant, email="sysrole-owner@test.test")
    owner.roles.add(roles["Owner"])
    client = APIClient()
    client.force_authenticate(user=owner)

    response = client.delete(f"/api/roles/{roles['Viewer'].id}/")
    assert response.status_code == 400


@pytest.mark.django_db
def test_role_assigned_to_a_user_cannot_be_deleted(tenant_with_roles):
    tenant, roles = tenant_with_roles
    owner = UserFactory(tenant=tenant, email="customrole-owner@test.test")
    owner.roles.add(roles["Owner"])
    client = APIClient()
    client.force_authenticate(user=owner)

    custom_role = RoleFactory(tenant=tenant, name="Custom", is_system=False)
    other_user = UserFactory(tenant=tenant, email="assignee@test.test")
    other_user.roles.add(custom_role)

    response = client.delete(f"/api/roles/{custom_role.id}/")
    assert response.status_code == 409


@pytest.mark.django_db
def test_unassigned_custom_role_can_be_deleted(tenant_with_roles):
    tenant, roles = tenant_with_roles
    owner = UserFactory(tenant=tenant, email="unassigned-owner@test.test")
    owner.roles.add(roles["Owner"])
    client = APIClient()
    client.force_authenticate(user=owner)

    custom_role = RoleFactory(tenant=tenant, name="Unused", is_system=False)
    response = client.delete(f"/api/roles/{custom_role.id}/")
    assert response.status_code == 204
