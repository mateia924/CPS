"""Regression tests for the cross-tenant login bypass found while
building this project (see README "قاعدة الأمان الأهم"): ModelBackend
resolves users by a *global* email lookup with no tenant filter, so if
it's ever re-added to AUTHENTICATION_BACKENDS, a login with the wrong
subdomain succeeds anyway as long as the email/password match a user in
ANY tenant. TenantEmailBackend must be the only backend configured, and
login must fail whenever the subdomain doesn't match the user's tenant.
"""

import pytest
from django.conf import settings
from rest_framework.test import APIClient


@pytest.fixture
def two_tenants(db):
    client = APIClient()
    resp_a = client.post(
        "/api/auth/register/",
        {
            "company_name": "Tenant A",
            "subdomain": "tenant-a",
            "email": "owner@tenant-a.test",
            "password": "S3curePass!2026",
        },
        format="json",
    )
    assert resp_a.status_code == 201, resp_a.content

    resp_b = client.post(
        "/api/auth/register/",
        {
            "company_name": "Tenant B",
            "subdomain": "tenant-b",
            "email": "owner@tenant-b.test",
            "password": "AnotherPass!2026",
        },
        format="json",
    )
    assert resp_b.status_code == 201, resp_b.content
    return resp_a.data, resp_b.data


def test_authentication_backends_never_include_model_backend():
    assert settings.AUTHENTICATION_BACKENDS == [
        "apps.accounts.backends.TenantEmailBackend"
    ]


def test_login_fails_with_wrong_subdomain_even_with_valid_other_tenant_credentials(
    two_tenants,
):
    client = APIClient()
    response = client.post(
        "/api/auth/login/",
        {
            "subdomain": "tenant-a",
            "email": "owner@tenant-b.test",
            "password": "AnotherPass!2026",
        },
        format="json",
    )
    assert response.status_code == 400


def test_login_succeeds_with_correct_subdomain(two_tenants):
    client = APIClient()
    response = client.post(
        "/api/auth/login/",
        {
            "subdomain": "tenant-b",
            "email": "owner@tenant-b.test",
            "password": "AnotherPass!2026",
        },
        format="json",
    )
    assert response.status_code == 200
    assert response.data["tenant"]["subdomain"] == "tenant-b"
