"""Sprint 7.2 (docs/prompts/sprint-7.md, block 7.2): warehouses, stock
levels, item cost per company, inventory settings. The four tests
this block's own spec names explicitly.
"""

from decimal import Decimal

import pytest

from apps.access.models import Role, UserEntityAccess
from apps.inventory.models import ItemCost, Warehouse
from apps.organization.models import LegalEntity
from apps.organization.services import company_entity_for
from apps.platform.models import Plan
from apps.tenants.services import apply_plan_to_tenant

from .factories import ProductFactory, UserFactory


def _enable_inventory(tenant):
    tenant.features.inventory = True
    tenant.features.save(update_fields=["inventory"])


# ---------------------------------------------------------------------
# A warehouse on a disallowed entity -> 404
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_warehouse_on_a_disallowed_entity_is_a_404(tenant_a, client_a, user_a):
    _enable_inventory(tenant_a)
    main = LegalEntity.objects.get(tenant=tenant_a, code="MAIN-01")
    other_company = LegalEntity.objects.create(
        tenant=tenant_a, code="OTHER", name="شركة أخرى", entity_type=LegalEntity.Type.COMPANY,
    )
    other_branch = LegalEntity.objects.create(
        tenant=tenant_a, code="OTHER-01", name="فرع آخر", entity_type=LegalEntity.Type.BRANCH,
        parent=other_company, country_code=other_company.country_code, base_currency=other_company.base_currency,
    )
    warehouse = Warehouse.objects.create(tenant=tenant_a, legal_entity=other_branch, code="W1", name="مستودع 1")

    # user_a (via the fixture) already seeded the default roles for
    # this tenant — seed_default_roles again would collide on the
    # unique (tenant, name) role constraint.
    accountant_role = Role.objects.get(tenant=tenant_a, name="Accountant")
    restricted = UserFactory(tenant=tenant_a, email="restricted@tenant-a.test")
    restricted.roles.add(accountant_role)
    UserEntityAccess.objects.create(user=restricted, legal_entity=main)  # access to MAIN only, not OTHER
    from rest_framework.test import APIClient

    restricted_client = APIClient()
    restricted_client.force_authenticate(user=restricted)

    resp = restricted_client.get(f"/api/warehouses/{warehouse.id}/")
    assert resp.status_code == 404


# ---------------------------------------------------------------------
# Two defaults in one entity -> 400; the atomic switch action works
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_two_default_warehouses_in_one_entity_is_rejected(tenant_a, client_a):
    _enable_inventory(tenant_a)
    main = LegalEntity.objects.get(tenant=tenant_a, code="MAIN-01")
    first = Warehouse.objects.create(tenant=tenant_a, legal_entity=main, code="W1", name="الأول", is_default=True)

    resp = client_a.post(
        "/api/warehouses/", {"legal_entity": str(main.id), "code": "W2", "name": "الثاني", "is_default": "true"},
    )
    assert resp.status_code == 400
    assert "is_default" in resp.data

    first.refresh_from_db()
    assert first.is_default is True  # the rejected attempt changed nothing


@pytest.mark.django_db
def test_set_default_action_is_the_atomic_switch(tenant_a, client_a):
    _enable_inventory(tenant_a)
    main = LegalEntity.objects.get(tenant=tenant_a, code="MAIN-01")
    first = Warehouse.objects.create(tenant=tenant_a, legal_entity=main, code="W1", name="الأول", is_default=True)
    second = Warehouse.objects.create(tenant=tenant_a, legal_entity=main, code="W2", name="الثاني")

    resp = client_a.post(f"/api/warehouses/{second.id}/set-default/")
    assert resp.status_code == 200, resp.data

    first.refresh_from_db()
    second.refresh_from_db()
    assert first.is_default is False
    assert second.is_default is True


# ---------------------------------------------------------------------
# The plan limit on warehouses rejects a second with the unified message
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_warehouse_plan_limit_rejects_the_second_with_the_unified_message(tenant_a, client_a):
    _enable_inventory(tenant_a)
    basic_plan = Plan.objects.create(code="basic-wh-test", name="Basic", max_warehouses=1)
    apply_plan_to_tenant(tenant_a, basic_plan)
    main = LegalEntity.objects.get(tenant=tenant_a, code="MAIN-01")
    Warehouse.objects.create(tenant=tenant_a, legal_entity=main, code="W1", name="الأول")

    resp = client_a.post("/api/warehouses/", {"legal_entity": str(main.id), "code": "W2", "name": "الثاني"})
    assert resp.status_code == 402
    assert "detail" in resp.data


# ---------------------------------------------------------------------
# A company with two branches: each branch its own warehouse, one
# ItemCost at the company level
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_company_with_two_branches_shares_one_item_cost(tenant_a):
    company = LegalEntity.objects.get(tenant=tenant_a, code="MAIN")
    branch1 = LegalEntity.objects.get(tenant=tenant_a, code="MAIN-01")
    branch2 = LegalEntity.objects.create(
        tenant=tenant_a, code="MAIN-02", name="فرع ثانٍ", entity_type=LegalEntity.Type.BRANCH,
        parent=company, country_code=company.country_code, base_currency=company.base_currency,
    )

    warehouse1 = Warehouse.objects.create(tenant=tenant_a, legal_entity=branch1, code="W1", name="مستودع الفرع الأول")
    warehouse2 = Warehouse.objects.create(tenant=tenant_a, legal_entity=branch2, code="W2", name="مستودع الفرع الثاني")
    assert warehouse1.legal_entity_id != warehouse2.legal_entity_id

    # Both branches resolve to the SAME company entity for costing.
    assert company_entity_for(branch1).id == company.id
    assert company_entity_for(branch2).id == company.id

    item = ProductFactory(tenant=tenant_a)
    cost = ItemCost.objects.create(
        tenant=tenant_a, item=item, company_entity=company,
        qty_on_hand=Decimal("10"), total_value=Decimal("100.00"), avg_cost=Decimal("10.00"),
    )
    # One ItemCost row serves both branches — a second create for the
    # same (item, company_entity) is refused by the DB's own constraint.
    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ItemCost.objects.create(tenant=tenant_a, item=item, company_entity=company, qty_on_hand=Decimal("5"))

    assert ItemCost.objects.filter(item=item, company_entity=company).count() == 1
    assert ItemCost.objects.get(item=item, company_entity=company).id == cost.id
