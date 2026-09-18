"""Tenant isolation is the single most important guarantee in this
project. docs/SYSTEM_ANALYSIS.md rule 1 (section 4): every query is
explicitly scoped to request.user.tenant; no API path accepts a
tenant_id from the client; access to another tenant's record returns
404, never 403 (403 would confirm the record exists in a tenant the
caller can't see, which is itself a leak).

This file also carries the regression coverage for a critical bug found
during initial development: django.contrib.auth.backends.ModelBackend
resolves users by a *global* User.objects.get(email=...) lookup with no
tenant filter. Since Django's authenticate() tries every configured
backend and accepts the first success, having ModelBackend anywhere in
AUTHENTICATION_BACKENDS lets a login with the WRONG subdomain succeed
anyway, as long as the email/password match a user in ANY tenant. See
config/settings.py's AUTHENTICATION_BACKENDS comment.

Every test in this file must keep passing before any sprint is closed
(docs/SYSTEM_ANALYSIS.md rule 8).
"""

import pytest
from django.conf import settings
from rest_framework.test import APIClient

from apps.organization.models import LegalEntity
from apps.sales.models import Customer, Product

from .factories import (
    CostCenterFactory,
    CustomerFactory,
    LegalEntityFactory,
    ProductFactory,
    RoleFactory,
    TenantFactory,
    UserFactory,
)

# ---------------------------------------------------------------------
# Regression: cross-tenant login bypass (ModelBackend)
# ---------------------------------------------------------------------


def test_authentication_backends_never_include_model_backend():
    assert settings.AUTHENTICATION_BACKENDS == [
        "apps.accounts.backends.TenantEmailBackend"
    ]


@pytest.mark.django_db
def test_login_fails_with_wrong_subdomain_even_with_valid_other_tenant_credentials():
    tenant_a = TenantFactory(subdomain="login-a")
    tenant_b = TenantFactory(subdomain="login-b")
    UserFactory(tenant=tenant_a, email="owner@a.test")
    UserFactory(tenant=tenant_b, email="owner@b.test", password="BPass!2026")

    response = APIClient().post(
        "/api/auth/login/",
        {"subdomain": "login-a", "email": "owner@b.test", "password": "BPass!2026"},
        format="json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_login_succeeds_with_correct_subdomain():
    tenant_b = TenantFactory(subdomain="login-b2")
    UserFactory(tenant=tenant_b, email="owner@b2.test", password="BPass!2026")

    response = APIClient().post(
        "/api/auth/login/",
        {"subdomain": "login-b2", "email": "owner@b2.test", "password": "BPass!2026"},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["tenant"]["subdomain"] == "login-b2"


# ---------------------------------------------------------------------
# List endpoints never leak another tenant's rows
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_customer_list_excludes_other_tenant(tenant_a, tenant_b, client_a):
    CustomerFactory(tenant=tenant_a, name="A's customer")
    CustomerFactory(tenant=tenant_b, name="B's customer")

    response = client_a.get("/api/customers/")
    assert response.status_code == 200
    names = [c["name"] for c in response.data["results"]]
    assert names == ["A's customer"]


@pytest.mark.django_db
def test_product_list_excludes_other_tenant(tenant_a, tenant_b, client_a):
    ProductFactory(tenant=tenant_a, sku="A-SKU")
    ProductFactory(tenant=tenant_b, sku="B-SKU")

    response = client_a.get("/api/products/")
    assert response.status_code == 200
    skus = [p["sku"] for p in response.data["results"]]
    assert skus == ["A-SKU"]


@pytest.mark.django_db
def test_invoice_list_excludes_other_tenant(tenant_a, tenant_b, client_a, client_b):
    customer_b = CustomerFactory(tenant=tenant_b)
    product_b = ProductFactory(tenant=tenant_b)
    created = client_b.post(
        "/api/invoices/",
        {
            "customer": str(customer_b.id),
            "lines": [{"product": str(product_b.id), "quantity": "1"}],
        },
        format="json",
    )
    assert created.status_code == 201

    response = client_a.get("/api/invoices/")
    assert response.status_code == 200
    assert response.data["results"] == []


# ---------------------------------------------------------------------
# Direct-by-ID access to another tenant's record -> 404, never 403
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_get_other_tenant_customer_returns_404_not_403(tenant_b, client_a):
    customer_b = CustomerFactory(tenant=tenant_b)
    response = client_a.get(f"/api/customers/{customer_b.id}/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_patch_other_tenant_customer_returns_404_and_does_not_modify(tenant_b, client_a):
    customer_b = CustomerFactory(tenant=tenant_b, name="Original")
    response = client_a.patch(
        f"/api/customers/{customer_b.id}/", {"name": "Hacked"}, format="json"
    )
    assert response.status_code == 404
    customer_b.refresh_from_db()
    assert customer_b.name == "Original"


@pytest.mark.django_db
def test_delete_other_tenant_customer_returns_404_and_does_not_delete(tenant_b, client_a):
    customer_b = CustomerFactory(tenant=tenant_b)
    response = client_a.delete(f"/api/customers/{customer_b.id}/")
    assert response.status_code == 404
    assert Customer.objects.filter(id=customer_b.id).exists()


@pytest.mark.django_db
def test_get_other_tenant_product_returns_404(tenant_b, client_a):
    product_b = ProductFactory(tenant=tenant_b)
    response = client_a.get(f"/api/products/{product_b.id}/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_delete_other_tenant_product_returns_404_and_does_not_delete(tenant_b, client_a):
    product_b = ProductFactory(tenant=tenant_b)
    response = client_a.delete(f"/api/products/{product_b.id}/")
    assert response.status_code == 404
    assert Product.objects.filter(id=product_b.id).exists()


@pytest.mark.django_db
def test_get_other_tenant_invoice_returns_404(tenant_a, tenant_b, client_a, client_b):
    customer_b = CustomerFactory(tenant=tenant_b)
    product_b = ProductFactory(tenant=tenant_b)
    created = client_b.post(
        "/api/invoices/",
        {
            "customer": str(customer_b.id),
            "lines": [{"product": str(product_b.id), "quantity": "1"}],
        },
        format="json",
    )
    assert created.status_code == 201

    response = client_a.get(f"/api/invoices/{created.data['id']}/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_issue_other_tenant_invoice_returns_404(tenant_a, tenant_b, client_a, client_b):
    customer_b = CustomerFactory(tenant=tenant_b)
    product_b = ProductFactory(tenant=tenant_b)
    created = client_b.post(
        "/api/invoices/",
        {
            "customer": str(customer_b.id),
            "lines": [{"product": str(product_b.id), "quantity": "1"}],
        },
        format="json",
    )
    assert created.status_code == 201

    response = client_a.post(f"/api/invoices/{created.data['id']}/issue/")
    assert response.status_code == 404


# ---------------------------------------------------------------------
# Creating an invoice referencing another tenant's customer/product is
# rejected — there is no tenant_id field anywhere for a client to spoof;
# tenant scoping happens by resolving each referenced id against
# request.user.tenant server-side (apps/sales/serializers.py).
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_create_invoice_with_other_tenant_customer_rejected(tenant_a, tenant_b, client_a):
    other_customer = CustomerFactory(tenant=tenant_b)
    own_product = ProductFactory(tenant=tenant_a)

    response = client_a.post(
        "/api/invoices/",
        {
            "customer": str(other_customer.id),
            "lines": [{"product": str(own_product.id), "quantity": "1"}],
        },
        format="json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_create_invoice_with_other_tenant_product_rejected(tenant_a, tenant_b, client_a):
    own_customer = CustomerFactory(tenant=tenant_a)
    other_product = ProductFactory(tenant=tenant_b)

    response = client_a.post(
        "/api/invoices/",
        {
            "customer": str(own_customer.id),
            "lines": [{"product": str(other_product.id), "quantity": "1"}],
        },
        format="json",
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------
# Sprint 1 models (LegalEntity, CostCenter, Role) go through the same
# isolation guarantees as everything else in this file.
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_legal_entity_list_excludes_other_tenant(tenant_a, tenant_b, client_a):
    LegalEntityFactory(tenant=tenant_b, code="B-ONLY")

    response = client_a.get("/api/legal-entities/")
    assert response.status_code == 200
    codes = [e["code"] for e in response.data["results"]]
    assert "B-ONLY" not in codes


@pytest.mark.django_db
def test_get_other_tenant_legal_entity_returns_404(tenant_b, client_a):
    entity_b = LegalEntityFactory(tenant=tenant_b)
    response = client_a.get(f"/api/legal-entities/{entity_b.id}/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_delete_other_tenant_legal_entity_returns_404_and_does_not_deactivate(tenant_b, client_a):
    entity_b = LegalEntityFactory(tenant=tenant_b)
    response = client_a.delete(f"/api/legal-entities/{entity_b.id}/")
    assert response.status_code == 404
    entity_b.refresh_from_db()
    assert entity_b.is_active is True


@pytest.mark.django_db
def test_create_legal_entity_with_other_tenant_parent_rejected(tenant_a, tenant_b, client_a):
    other_parent = LegalEntityFactory(tenant=tenant_b, entity_type=LegalEntity.Type.COMPANY)
    response = client_a.post(
        "/api/legal-entities/",
        {"code": "NEW", "name": "New Co", "entity_type": "branch", "parent": str(other_parent.id)},
        format="json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_cost_center_list_excludes_other_tenant(tenant_a, tenant_b, client_a):
    CostCenterFactory(tenant=tenant_b, code="B-CC")

    response = client_a.get("/api/cost-centers/")
    assert response.status_code == 200
    codes = [c["code"] for c in response.data["results"]]
    assert "B-CC" not in codes


@pytest.mark.django_db
def test_get_other_tenant_cost_center_returns_404(tenant_b, client_a):
    center_b = CostCenterFactory(tenant=tenant_b)
    response = client_a.get(f"/api/cost-centers/{center_b.id}/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_role_list_excludes_other_tenant(tenant_a, tenant_b, client_a):
    RoleFactory(tenant=tenant_b, name="B-Only-Role")

    response = client_a.get("/api/roles/")
    assert response.status_code == 200
    names = [r["name"] for r in response.data["results"]]
    assert "B-Only-Role" not in names


@pytest.mark.django_db
def test_get_other_tenant_role_returns_404(tenant_b, client_a):
    role_b = RoleFactory(tenant=tenant_b)
    response = client_a.get(f"/api/roles/{role_b.id}/")
    assert response.status_code == 404
