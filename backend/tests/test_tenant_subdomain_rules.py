"""Sprint 6.9.1 (item I, decision 7): "معرّف الشركة" (Tenant.subdomain)
rules — normalized to lowercase, 3-30 chars of Latin letters/digits/
hyphens (never starting or ending with one), a fixed reserved-name
list, unique, and never changeable after creation via any API.
"""

import pyotp
import pytest
from rest_framework.test import APIClient

from apps.platform.serializers import TenantAdminSerializer
from apps.tenants.models import Tenant

from .factories import PlatformUserFactory, TenantFactory


def _register(subdomain, email="owner@subdomain-rules.test"):
    client = APIClient()
    response = client.post(
        "/api/auth/register/",
        {
            "company_name": "Subdomain Rules Co",
            "subdomain": subdomain,
            "email": email,
            "password": "SubdomainRulesPass!2026",
        },
        format="json",
    )
    return response


@pytest.mark.django_db
def test_reserved_subdomain_rejected():
    response = _register("admin")
    assert response.status_code == 400, response.data
    assert "subdomain" in response.data


@pytest.mark.django_db
def test_uppercase_is_normalized_to_lowercase():
    response = _register("SubdomainCase")
    assert response.status_code == 201, response.data
    assert Tenant.objects.filter(subdomain="subdomaincase").exists()


@pytest.mark.django_db
def test_leading_or_trailing_hyphen_rejected():
    assert _register("-leading").status_code == 400
    assert _register("trailing-").status_code == 400


@pytest.mark.django_db
def test_non_latin_character_rejected():
    response = _register("شركة")
    assert response.status_code == 400, response.data


@pytest.mark.django_db
def test_too_short_or_too_long_rejected():
    assert _register("ab").status_code == 400
    assert _register("a" * 31).status_code == 400


@pytest.mark.django_db
def test_duplicate_subdomain_rejected():
    TenantFactory(subdomain="already-taken")
    response = _register("already-taken")
    assert response.status_code == 400, response.data


@pytest.mark.django_db
def test_valid_subdomain_succeeds():
    response = _register("valid-company-99")
    assert response.status_code == 201, response.data
    assert response.data["tenant"]["subdomain"] == "valid-company-99"


@pytest.mark.django_db(databases=["default", "platform"])
def test_subdomain_cannot_be_changed_after_creation():
    tenant = TenantFactory(subdomain="immutable-co")
    platform_user = PlatformUserFactory(password="PlatformPass!2026")
    client = APIClient()
    login = client.post(
        "/api/platform/auth/login/",
        {
            "email": platform_user.email, "password": "PlatformPass!2026",
            "totp_code": pyotp.TOTP(platform_user.totp_secret).now(),
        },
        format="json",
    )
    assert login.status_code == 200, login.data
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

    # No PATCH/PUT route exists on this ViewSet at all (subdomain is
    # immutable by construction, not by a field-level check alone).
    response = client.patch(f"/api/platform/tenants/{tenant.id}/", {"subdomain": "renamed-co"}, format="json")
    assert response.status_code == 405

    # Even a direct serializer write (bypassing the missing route)
    # can't move it — the field is read-only.
    serializer = TenantAdminSerializer(instance=tenant, data={"subdomain": "renamed-co"}, partial=True)
    assert serializer.is_valid(), serializer.errors
    serializer.save()
    tenant.refresh_from_db()
    assert tenant.subdomain == "immutable-co"
