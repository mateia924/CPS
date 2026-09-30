"""Sprint 6.6.1 (item 5): functional proof — not just the structural
test (test_entity_scope_structural.py) that every relevant ViewSet
inherits the mixin, but that the mixin itself actually blocks a real
request. A user restricted to one legal entity (branch) must never
see, edit, or act on another entity's row by id — 404, never 403 (same
"a scope violation looks like it doesn't exist" convention as every
other scope check in this codebase) — while the Owner, who has no
UserEntityAccess restriction at all, sees everything. Covers the four
gaps this block's own Mixin actually closes (Asset/Bank/CashBox/
Custody had NO entity-scoping before this sprint) plus LegalEntity
itself (its own "id"-lookup case). Real HTTP API + real Postgres
throughout (§11)."""

import pytest
from rest_framework.test import APIClient

from apps.access.models import Permission, Role, UserEntityAccess
from apps.access.services import seed_default_roles, seed_permissions

from .factories import AssetFactory, LegalEntityFactory, UserFactory


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _roles(tenant):
    existing = {r.name: r for r in Role.objects.filter(tenant=tenant, is_system=True)}
    return existing or seed_default_roles(tenant)


def _restricted_user(tenant, entity, extra_permissions=()):
    user = UserFactory(tenant=tenant, email=f"restricted-{entity.id}@entity-scope.test")
    user.roles.add(_roles(tenant)["Accountant"])
    if extra_permissions:
        # The system "Accountant" role has no write permission on some
        # modules (e.g. assets.manage) — no default non-Owner role does.
        # A dedicated one-off role isolates the entity-scope assertion
        # from the separate (and here irrelevant) permission dimension.
        seed_permissions()
        extra_role = Role.objects.create(tenant=tenant, name=f"entity-scope-test-{entity.id}")
        extra_role.permissions.add(*Permission.objects.filter(code__in=extra_permissions))
        user.roles.add(extra_role)
    UserEntityAccess.objects.create(user=user, legal_entity=entity)
    return user


@pytest.mark.django_db
def test_asset_list_retrieve_update_dispose_scoped_by_entity(tenant_a, user_a):
    entity_a = LegalEntityFactory(tenant=tenant_a)
    entity_b = LegalEntityFactory(tenant=tenant_a)
    asset_a = AssetFactory(tenant=tenant_a, legal_entity=entity_a, purchase_date="2026-01-01", purchase_cost="1000.00")
    asset_b = AssetFactory(tenant=tenant_a, legal_entity=entity_b, purchase_date="2026-01-01", purchase_cost="2000.00")

    owner_client = _client(user_a)
    owner_list = owner_client.get("/api/assets/")
    owner_ids = {row["id"] for row in owner_list.data["results"]}
    assert {str(asset_a.id), str(asset_b.id)} <= owner_ids

    restricted_client = _client(_restricted_user(tenant_a, entity_a, extra_permissions=["assets.manage"]))

    restricted_list = restricted_client.get("/api/assets/")
    restricted_ids = {row["id"] for row in restricted_list.data["results"]}
    assert str(asset_a.id) in restricted_ids
    assert str(asset_b.id) not in restricted_ids

    own_entity = restricted_client.get(f"/api/assets/{asset_a.id}/")
    assert own_entity.status_code == 200, own_entity.data

    other_entity_retrieve = restricted_client.get(f"/api/assets/{asset_b.id}/")
    assert other_entity_retrieve.status_code == 404, other_entity_retrieve.data

    other_entity_update = restricted_client.patch(f"/api/assets/{asset_b.id}/", {"name": "x"}, format="json")
    assert other_entity_update.status_code == 404, other_entity_update.data

    other_entity_dispose = restricted_client.post(
        f"/api/assets/{asset_b.id}/dispose/", {"date": "2026-06-01", "fraction": "1"}, format="json",
    )
    assert other_entity_dispose.status_code == 404, other_entity_dispose.data


@pytest.mark.django_db
def test_bank_list_and_retrieve_scoped_by_entity(tenant_a, user_a):
    entity_a = LegalEntityFactory(tenant=tenant_a)
    entity_b = LegalEntityFactory(tenant=tenant_a)
    owner_client = _client(user_a)

    bank_a = owner_client.post(
        "/api/banks/", {"legal_entity": str(entity_a.id), "name": "Bank A", "currency": "SAR"}, format="json",
    ).data
    bank_b = owner_client.post(
        "/api/banks/", {"legal_entity": str(entity_b.id), "name": "Bank B", "currency": "SAR"}, format="json",
    ).data

    restricted_client = _client(_restricted_user(tenant_a, entity_a))

    restricted_list = restricted_client.get("/api/banks/")
    restricted_ids = {row["id"] for row in restricted_list.data["results"]}
    assert bank_a["id"] in restricted_ids
    assert bank_b["id"] not in restricted_ids

    assert restricted_client.get(f"/api/banks/{bank_a['id']}/").status_code == 200
    assert restricted_client.get(f"/api/banks/{bank_b['id']}/").status_code == 404


@pytest.mark.django_db
def test_legal_entity_list_and_retrieve_scoped_to_accessible_entities(tenant_a, user_a):
    entity_a = LegalEntityFactory(tenant=tenant_a)
    entity_b = LegalEntityFactory(tenant=tenant_a)

    owner_client = _client(user_a)
    owner_list = owner_client.get("/api/legal-entities/")
    owner_ids = {row["id"] for row in owner_list.data["results"]}
    assert {str(entity_a.id), str(entity_b.id)} <= owner_ids

    restricted_client = _client(_restricted_user(tenant_a, entity_a))
    restricted_list = restricted_client.get("/api/legal-entities/")
    restricted_ids = {row["id"] for row in restricted_list.data["results"]}
    assert str(entity_a.id) in restricted_ids
    assert str(entity_b.id) not in restricted_ids

    assert restricted_client.get(f"/api/legal-entities/{entity_a.id}/").status_code == 200
    assert restricted_client.get(f"/api/legal-entities/{entity_b.id}/").status_code == 404
