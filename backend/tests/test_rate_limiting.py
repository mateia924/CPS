"""Sprint 4.0 (ARCH_REVIEW_1.md debt #9): django-ratelimit layer inside
apps.common.ratelimit, behind nginx's IP-only limit_req (infra/nginx/
nginx.conf — not exercised here, this suite never runs through nginx).

RATELIMIT_ENABLE is off by default for the whole suite (see conftest.py)
because dozens of other tests call these same endpoints far more than
5 times/minute; each test below turns it back on for itself only.
"""

import pyotp
import pytest
from rest_framework.test import APIClient

from .factories import PlatformUserFactory, TenantFactory, UserFactory

PASSWORD = "TestPass!2026"


@pytest.mark.django_db
def test_login_is_rate_limited_after_5_attempts_per_ip_and_email(settings):
    settings.RATELIMIT_ENABLE = True
    tenant = TenantFactory(subdomain="ratelimit-login")
    UserFactory(tenant=tenant, email="user@ratelimit-login.test", password=PASSWORD)
    client = APIClient()
    payload = {
        "subdomain": "ratelimit-login",
        "email": "user@ratelimit-login.test",
        "password": "WrongPassword!",
    }

    responses = [client.post("/api/auth/login/", payload, format="json") for _ in range(6)]

    assert [r.status_code for r in responses[:5]] == [400] * 5
    assert responses[5].status_code == 429
    assert "detail" in responses[5].data


@pytest.mark.django_db
def test_login_rate_limit_is_scoped_per_email_not_just_per_ip(settings):
    settings.RATELIMIT_ENABLE = True
    tenant = TenantFactory(subdomain="ratelimit-scope")
    UserFactory(tenant=tenant, email="victim@ratelimit-scope.test", password=PASSWORD)
    UserFactory(tenant=tenant, email="other@ratelimit-scope.test", password=PASSWORD)
    client = APIClient()
    victim_payload = {
        "subdomain": "ratelimit-scope",
        "email": "victim@ratelimit-scope.test",
        "password": "Wrong!",
    }
    for _ in range(5):
        client.post("/api/auth/login/", victim_payload, format="json")

    other_response = client.post(
        "/api/auth/login/",
        {"subdomain": "ratelimit-scope", "email": "other@ratelimit-scope.test", "password": PASSWORD},
        format="json",
    )

    assert other_response.status_code == 200


@pytest.mark.django_db
def test_register_is_rate_limited_after_5_attempts(settings):
    settings.RATELIMIT_ENABLE = True
    client = APIClient()
    payload = {
        "company_name": "Ratelimit Co",
        "subdomain": "ratelimit-register",
        "email": "founder@ratelimit-register.test",
        "password": "not-valid",
    }

    responses = [client.post("/api/auth/register/", payload, format="json") for _ in range(6)]

    assert responses[5].status_code == 429


@pytest.mark.django_db
def test_platform_login_is_rate_limited_after_5_attempts(settings):
    settings.RATELIMIT_ENABLE = True
    platform_user = PlatformUserFactory(password="PlatformPass!2026")
    client = APIClient()
    payload = {
        "email": platform_user.email,
        "password": "WrongPlatformPassword!",
        "totp_code": pyotp.TOTP(platform_user.totp_secret).now(),
    }

    responses = [client.post("/api/platform/auth/login/", payload, format="json") for _ in range(6)]

    assert responses[5].status_code == 429
