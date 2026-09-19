"""Sprint 1.5 rule 3: an entity with transactions is only ever
deactivated, never actually deleted; an actual-delete attempt on one
returns 409. An entity with zero references really is deletable, and
deactivate/activate always work regardless of references.
"""

import pytest

from apps.organization.models import CostCenter, LegalEntity
from apps.parties.models import Party
from apps.sales.models import Customer, Product

from .factories import (
    CostCenterFactory,
    CustomerFactory,
    LegalEntityFactory,
    PartyFactory,
    ProductFactory,
)


@pytest.mark.django_db
def test_customer_patch_succeeds(tenant_a, client_a):
    customer = CustomerFactory(tenant=tenant_a, name="Original")
    response = client_a.patch(f"/api/customers/{customer.id}/", {"name": "Renamed"}, format="json")
    assert response.status_code == 200
    assert response.data["name"] == "Renamed"


@pytest.mark.django_db
def test_customer_deactivate_then_activate(tenant_a, client_a):
    customer = CustomerFactory(tenant=tenant_a)

    response = client_a.post(f"/api/customers/{customer.id}/deactivate/")
    assert response.status_code == 200
    assert response.data["is_active"] is False
    customer.refresh_from_db()
    assert customer.is_active is False

    response = client_a.post(f"/api/customers/{customer.id}/activate/")
    assert response.status_code == 200
    assert response.data["is_active"] is True


@pytest.mark.django_db
def test_customer_list_hides_inactive_by_default(tenant_a, client_a):
    CustomerFactory(tenant=tenant_a, name="Active One", is_active=True)
    CustomerFactory(tenant=tenant_a, name="Inactive One", is_active=False)

    response = client_a.get("/api/customers/")
    names = [c["name"] for c in response.data["results"]]
    assert "Active One" in names
    assert "Inactive One" not in names

    response = client_a.get("/api/customers/?show_inactive=true")
    names = [c["name"] for c in response.data["results"]]
    assert "Inactive One" in names


@pytest.mark.django_db
def test_delete_party_with_invoice_returns_409(tenant_a, client_a):
    # Sprint 3: invoices reference a Party (role=CUSTOMER) now, not the
    # legacy Customer model — see test_delete_customer_without_invoice_
    # actually_deletes below for the (still-live, unaffected) old
    # Customer endpoint.
    customer = PartyFactory(tenant=tenant_a)
    product = ProductFactory(tenant=tenant_a)
    created = client_a.post(
        "/api/invoices/",
        {"customer": str(customer.id), "lines": [{"product": str(product.id), "quantity": "1"}]},
        format="json",
    )
    assert created.status_code == 201

    response = client_a.delete(f"/api/parties/{customer.id}/")
    assert response.status_code == 409
    assert Party.objects.filter(id=customer.id).exists()


@pytest.mark.django_db
def test_delete_customer_without_invoice_actually_deletes(tenant_a, client_a):
    customer = CustomerFactory(tenant=tenant_a)
    response = client_a.delete(f"/api/customers/{customer.id}/")
    assert response.status_code == 204
    assert not Customer.objects.filter(id=customer.id).exists()


@pytest.mark.django_db
def test_delete_product_used_in_invoice_line_returns_409(tenant_a, client_a):
    customer = PartyFactory(tenant=tenant_a)
    product = ProductFactory(tenant=tenant_a)
    created = client_a.post(
        "/api/invoices/",
        {"customer": str(customer.id), "lines": [{"product": str(product.id), "quantity": "1"}]},
        format="json",
    )
    assert created.status_code == 201

    response = client_a.delete(f"/api/products/{product.id}/")
    assert response.status_code == 409
    assert Product.objects.filter(id=product.id).exists()


@pytest.mark.django_db
def test_delete_unused_product_actually_deletes(tenant_a, client_a):
    product = ProductFactory(tenant=tenant_a)
    response = client_a.delete(f"/api/products/{product.id}/")
    assert response.status_code == 204
    assert not Product.objects.filter(id=product.id).exists()


@pytest.mark.django_db
def test_delete_legal_entity_used_by_invoice_returns_409(tenant_a, client_a):
    # tenant_a's fixture-provided branch already has invoices in some
    # tests, but build a fresh, unambiguous one here.
    company = LegalEntityFactory(tenant=tenant_a, entity_type=LegalEntity.Type.COMPANY)
    branch = LegalEntityFactory(
        tenant=tenant_a, entity_type=LegalEntity.Type.BRANCH, parent=company
    )
    customer = PartyFactory(tenant=tenant_a)
    product = ProductFactory(tenant=tenant_a)
    created = client_a.post(
        "/api/invoices/",
        {
            "customer": str(customer.id),
            "legal_entity": str(branch.id),
            "lines": [{"product": str(product.id), "quantity": "1"}],
        },
        format="json",
    )
    assert created.status_code == 201

    response = client_a.delete(f"/api/legal-entities/{branch.id}/")
    assert response.status_code == 409
    assert LegalEntity.objects.filter(id=branch.id).exists()


@pytest.mark.django_db
def test_delete_legal_entity_with_children_returns_409(tenant_a, client_a):
    company = LegalEntityFactory(tenant=tenant_a, entity_type=LegalEntity.Type.COMPANY)
    LegalEntityFactory(tenant=tenant_a, entity_type=LegalEntity.Type.BRANCH, parent=company)

    response = client_a.delete(f"/api/legal-entities/{company.id}/")
    assert response.status_code == 409


@pytest.mark.django_db
def test_legal_entity_deactivate_reactivate(tenant_a, client_a):
    entity = LegalEntityFactory(tenant=tenant_a, entity_type=LegalEntity.Type.COMPANY)

    response = client_a.post(f"/api/legal-entities/{entity.id}/deactivate/")
    assert response.status_code == 200
    assert response.data["is_active"] is False

    response = client_a.post(f"/api/legal-entities/{entity.id}/activate/")
    assert response.status_code == 200
    assert response.data["is_active"] is True


@pytest.mark.django_db
def test_delete_unused_legal_entity_actually_deletes(tenant_a, client_a):
    entity = LegalEntityFactory(tenant=tenant_a, entity_type=LegalEntity.Type.COMPANY)
    response = client_a.delete(f"/api/legal-entities/{entity.id}/")
    assert response.status_code == 204
    assert not LegalEntity.objects.filter(id=entity.id).exists()


@pytest.mark.django_db
def test_delete_cost_center_used_by_invoice_line_returns_409(tenant_a, client_a):
    customer = PartyFactory(tenant=tenant_a)
    product = ProductFactory(tenant=tenant_a)
    cost_center = CostCenterFactory(tenant=tenant_a)
    created = client_a.post(
        "/api/invoices/",
        {
            "customer": str(customer.id),
            "lines": [
                {"product": str(product.id), "quantity": "1", "cost_center": str(cost_center.id)}
            ],
        },
        format="json",
    )
    assert created.status_code == 201

    response = client_a.delete(f"/api/cost-centers/{cost_center.id}/")
    assert response.status_code == 409
    assert CostCenter.objects.filter(id=cost_center.id).exists()


@pytest.mark.django_db
def test_delete_unused_cost_center_actually_deletes(tenant_a, client_a):
    cost_center = CostCenterFactory(tenant=tenant_a)
    response = client_a.delete(f"/api/cost-centers/{cost_center.id}/")
    assert response.status_code == 204
    assert not CostCenter.objects.filter(id=cost_center.id).exists()
