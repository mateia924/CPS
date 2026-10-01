"""Sprint 1.5 rule 3 / sprint 6.6.5 (owner decision 29 Sept, unified
delete rule): an entity with transactions is only ever deactivated,
never actually deleted; an actual-delete attempt on one returns 409.
An entity with zero references is SOFT-deleted (`deleted_at`/
`deleted_by` set, apps.common.models.SoftDeleteModelMixin) — never a
real SQL DELETE, anywhere, since 6.6.5 ("لا DELETE فعلي في أي مكان") —
and disappears from the API (list AND retrieve) entirely, with no
"show deleted" escape hatch (unlike `?show_inactive=true` for
deactivated rows, which still have a reactivation path). deactivate/
activate always work regardless of references, unchanged.
"""

import pytest

from apps.accounting.models import TaxCode
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
    tax_code = TaxCode.objects.get(tenant=tenant_a, code="S")
    created = client_a.post(
        "/api/invoices/",
        {
            "customer": str(customer.id),
            "lines": [{"product": str(product.id), "quantity": "1", "tax_code": str(tax_code.id)}],
        },
        format="json",
    )
    assert created.status_code == 201

    response = client_a.delete(f"/api/parties/{customer.id}/")
    assert response.status_code == 409
    assert Party.objects.filter(id=customer.id).exists()


@pytest.mark.django_db
def test_delete_customer_without_invoice_soft_deletes(tenant_a, client_a):
    customer = CustomerFactory(tenant=tenant_a)
    response = client_a.delete(f"/api/customers/{customer.id}/")
    assert response.status_code == 204

    customer.refresh_from_db()
    assert customer.deleted_at is not None
    assert Customer.objects.filter(id=customer.id).exists()  # soft delete — no real DELETE, ever

    assert client_a.get(f"/api/customers/{customer.id}/").status_code == 404
    names = [c["name"] for c in client_a.get("/api/customers/").data["results"]]
    assert customer.name not in names


@pytest.mark.django_db
def test_delete_product_used_in_invoice_line_returns_409(tenant_a, client_a):
    customer = PartyFactory(tenant=tenant_a)
    product = ProductFactory(tenant=tenant_a)
    tax_code = TaxCode.objects.get(tenant=tenant_a, code="S")
    created = client_a.post(
        "/api/invoices/",
        {
            "customer": str(customer.id),
            "lines": [{"product": str(product.id), "quantity": "1", "tax_code": str(tax_code.id)}],
        },
        format="json",
    )
    assert created.status_code == 201

    response = client_a.delete(f"/api/products/{product.id}/")
    assert response.status_code == 409
    assert Product.objects.filter(id=product.id).exists()


@pytest.mark.django_db
def test_delete_unused_product_soft_deletes(tenant_a, client_a):
    product = ProductFactory(tenant=tenant_a)
    response = client_a.delete(f"/api/products/{product.id}/")
    assert response.status_code == 204

    product.refresh_from_db()
    assert product.deleted_at is not None
    assert Product.objects.filter(id=product.id).exists()
    assert client_a.get(f"/api/products/{product.id}/").status_code == 404


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
    tax_code = TaxCode.objects.get(tenant=tenant_a, code="S")
    created = client_a.post(
        "/api/invoices/",
        {
            "customer": str(customer.id),
            "legal_entity": str(branch.id),
            "lines": [{"product": str(product.id), "quantity": "1", "tax_code": str(tax_code.id)}],
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
def test_delete_unused_legal_entity_soft_deletes(tenant_a, client_a):
    entity = LegalEntityFactory(tenant=tenant_a, entity_type=LegalEntity.Type.COMPANY)
    response = client_a.delete(f"/api/legal-entities/{entity.id}/")
    assert response.status_code == 204

    entity.refresh_from_db()
    assert entity.deleted_at is not None
    assert LegalEntity.objects.filter(id=entity.id).exists()
    assert client_a.get(f"/api/legal-entities/{entity.id}/").status_code == 404


@pytest.mark.django_db
def test_delete_cost_center_used_by_invoice_line_returns_409(tenant_a, client_a):
    customer = PartyFactory(tenant=tenant_a)
    product = ProductFactory(tenant=tenant_a)
    cost_center = CostCenterFactory(tenant=tenant_a)
    tax_code = TaxCode.objects.get(tenant=tenant_a, code="S")
    created = client_a.post(
        "/api/invoices/",
        {
            "customer": str(customer.id),
            "lines": [
                {
                    "product": str(product.id), "quantity": "1", "cost_center": str(cost_center.id),
                    "tax_code": str(tax_code.id),
                }
            ],
        },
        format="json",
    )
    assert created.status_code == 201

    response = client_a.delete(f"/api/cost-centers/{cost_center.id}/")
    assert response.status_code == 409
    assert CostCenter.objects.filter(id=cost_center.id).exists()


@pytest.mark.django_db
def test_delete_unused_cost_center_soft_deletes(tenant_a, client_a):
    cost_center = CostCenterFactory(tenant=tenant_a)
    response = client_a.delete(f"/api/cost-centers/{cost_center.id}/")
    assert response.status_code == 204

    cost_center.refresh_from_db()
    assert cost_center.deleted_at is not None
    assert CostCenter.objects.filter(id=cost_center.id).exists()
    assert client_a.get(f"/api/cost-centers/{cost_center.id}/").status_code == 404


@pytest.mark.django_db
def test_soft_deleted_record_records_who_deleted_it(tenant_a, client_a, user_a):
    cost_center = CostCenterFactory(tenant=tenant_a)
    client_a.delete(f"/api/cost-centers/{cost_center.id}/")
    cost_center.refresh_from_db()
    assert cost_center.deleted_by_id == user_a.id
