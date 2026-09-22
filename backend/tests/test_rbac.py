"""docs/SYSTEM_ANALYSIS.md 3.14 / sprint 1 section 3: role-based
permissions and legal-entity scoping. A Viewer inside their own tenant
correctly gets 403 (they're not looking at someone else's data — the
403-vs-404 distinction from test_tenant_isolation.py is specifically
about cross-tenant access, not in-tenant permission checks).
"""

import pytest
from rest_framework.test import APIClient

from apps.access.models import UserEntityAccess
from apps.access.services import seed_default_roles
from apps.accounting.models import TaxCode
from apps.accounting.services import seed_chart_of_accounts, seed_tax_codes_for_country
from apps.organization.models import LegalEntity

from .factories import PartyFactory, ProductFactory, TenantFactory, UserFactory


@pytest.fixture
def tenant_with_two_branches(db):
    tenant = TenantFactory(subdomain="rbac-tenant")
    company = LegalEntity.objects.create(
        tenant=tenant, code="MAIN", name="Main Co", entity_type=LegalEntity.Type.COMPANY
    )
    branch_a = LegalEntity.objects.create(
        tenant=tenant, code="BR-A", name="Branch A", entity_type=LegalEntity.Type.BRANCH, parent=company
    )
    branch_b = LegalEntity.objects.create(
        tenant=tenant, code="BR-B", name="Branch B", entity_type=LegalEntity.Type.BRANCH, parent=company
    )
    seed_chart_of_accounts(tenant)
    seed_tax_codes_for_country(tenant, "SA")
    return tenant, branch_a, branch_b


@pytest.mark.django_db
def test_viewer_role_cannot_create_invoice(tenant_with_two_branches):
    tenant, branch_a, _branch_b = tenant_with_two_branches
    roles = seed_default_roles(tenant)
    user = UserFactory(tenant=tenant, email="viewer@rbac.test")
    user.roles.add(roles["Viewer"])
    UserEntityAccess.objects.create(user=user, legal_entity=branch_a)

    client = APIClient()
    client.force_authenticate(user=user)

    customer = PartyFactory(tenant=tenant)
    product = ProductFactory(tenant=tenant)
    response = client.post(
        "/api/invoices/",
        {
            "customer": str(customer.id),
            "legal_entity": str(branch_a.id),
            "lines": [{"product": str(product.id), "quantity": "1"}],
        },
        format="json",
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_viewer_can_still_view_invoices(tenant_with_two_branches):
    tenant, branch_a, _branch_b = tenant_with_two_branches
    roles = seed_default_roles(tenant)
    user = UserFactory(tenant=tenant, email="viewer2@rbac.test")
    user.roles.add(roles["Viewer"])
    UserEntityAccess.objects.create(user=user, legal_entity=branch_a)

    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/invoices/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_entity_restricted_user_cannot_see_other_branch_invoices(tenant_with_two_branches):
    tenant, branch_a, branch_b = tenant_with_two_branches
    roles = seed_default_roles(tenant)

    owner = UserFactory(tenant=tenant, email="owner@rbac.test")
    owner.roles.add(roles["Owner"])
    owner_client = APIClient()
    owner_client.force_authenticate(user=owner)

    customer = PartyFactory(tenant=tenant)
    product = ProductFactory(tenant=tenant)
    tax_code = TaxCode.objects.get(tenant=tenant, code="S")
    created = owner_client.post(
        "/api/invoices/",
        {
            "customer": str(customer.id),
            "legal_entity": str(branch_b.id),
            "lines": [{"product": str(product.id), "quantity": "1", "tax_code": str(tax_code.id)}],
        },
        format="json",
    )
    assert created.status_code == 201
    invoice_id = created.data["id"]

    restricted_user = UserFactory(tenant=tenant, email="restricted@rbac.test")
    restricted_user.roles.add(roles["Accountant"])
    UserEntityAccess.objects.create(user=restricted_user, legal_entity=branch_a)
    restricted_client = APIClient()
    restricted_client.force_authenticate(user=restricted_user)

    detail_response = restricted_client.get(f"/api/invoices/{invoice_id}/")
    assert detail_response.status_code == 404

    list_response = restricted_client.get("/api/invoices/")
    assert list_response.status_code == 200
    assert list_response.data["results"] == []


@pytest.mark.django_db
def test_owner_bypasses_entity_access_and_sees_both_branches(tenant_with_two_branches):
    tenant, branch_a, branch_b = tenant_with_two_branches
    roles = seed_default_roles(tenant)

    owner = UserFactory(tenant=tenant, email="owner2@rbac.test")
    owner.roles.add(roles["Owner"])
    client = APIClient()
    client.force_authenticate(user=owner)

    customer = PartyFactory(tenant=tenant)
    product = ProductFactory(tenant=tenant)
    tax_code = TaxCode.objects.get(tenant=tenant, code="S")
    for branch in (branch_a, branch_b):
        response = client.post(
            "/api/invoices/",
            {
                "customer": str(customer.id),
                "legal_entity": str(branch.id),
                "lines": [{"product": str(product.id), "quantity": "1", "tax_code": str(tax_code.id)}],
            },
            format="json",
        )
        assert response.status_code == 201

    list_response = client.get("/api/invoices/")
    assert list_response.data["count"] == 2
