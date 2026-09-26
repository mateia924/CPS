"""Sprint 4.0 (ARCH_REVIEW_1.md debt #9): django-ratelimit layer inside
apps.common.ratelimit, behind nginx's IP-only limit_req (infra/nginx/
nginx.conf — not exercised here, this suite never runs through nginx).

RATELIMIT_ENABLE is off by default for the whole suite (see conftest.py)
because dozens of other tests call these same endpoints far more than
5 times/minute; each test below turns it back on for itself only.

Sprint 6.9.1 (item G): the rate-limit counter lives in Redis, keyed on
(client IP, email) with a rolling window — every test here always used
the same client IP (the test client's fixed REMOTE_ADDR) and the same
literal email string, so re-running this file (or the full suite)
twice within that window left stale counts from the previous run,
making "the first 5 attempts succeed" flaky depending on timing rather
than logic. Every email below now carries a random suffix
(`uuid.uuid4().hex[:8]`) so each test run always starts a fresh key —
no shared fixture needed, no risk of flushing the real Redis db (also
Celery's broker) between tests.
"""

import uuid

import pyotp
import pytest
from rest_framework.test import APIClient

from .factories import PlatformUserFactory, TenantFactory, UserFactory

PASSWORD = "TestPass!2026"


def _unique(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.mark.django_db
def test_login_is_rate_limited_after_5_attempts_per_ip_and_email(settings):
    settings.RATELIMIT_ENABLE = True
    subdomain = _unique("ratelimit-login")
    email = f"user@{subdomain}.test"
    tenant = TenantFactory(subdomain=subdomain)
    UserFactory(tenant=tenant, email=email, password=PASSWORD)
    client = APIClient()
    payload = {"subdomain": subdomain, "email": email, "password": "WrongPassword!"}

    responses = [client.post("/api/auth/login/", payload, format="json") for _ in range(6)]

    assert [r.status_code for r in responses[:5]] == [400] * 5
    assert responses[5].status_code == 429
    assert "detail" in responses[5].data


@pytest.mark.django_db
def test_login_rate_limit_is_scoped_per_email_not_just_per_ip(settings):
    settings.RATELIMIT_ENABLE = True
    subdomain = _unique("ratelimit-scope")
    victim_email = f"victim@{subdomain}.test"
    other_email = f"other@{subdomain}.test"
    tenant = TenantFactory(subdomain=subdomain)
    UserFactory(tenant=tenant, email=victim_email, password=PASSWORD)
    UserFactory(tenant=tenant, email=other_email, password=PASSWORD)
    client = APIClient()
    victim_payload = {"subdomain": subdomain, "email": victim_email, "password": "Wrong!"}
    for _ in range(5):
        client.post("/api/auth/login/", victim_payload, format="json")

    other_response = client.post(
        "/api/auth/login/",
        {"subdomain": subdomain, "email": other_email, "password": PASSWORD},
        format="json",
    )

    assert other_response.status_code == 200


@pytest.mark.django_db
def test_register_is_rate_limited_after_5_attempts(settings):
    settings.RATELIMIT_ENABLE = True
    client = APIClient()
    subdomain = _unique("ratelimit-register")
    payload = {
        "company_name": "Ratelimit Co",
        "subdomain": subdomain,
        "email": f"founder@{subdomain}.test",
        "password": "not-valid",
    }

    responses = [client.post("/api/auth/register/", payload, format="json") for _ in range(6)]

    assert responses[5].status_code == 429


@pytest.mark.django_db
def test_platform_login_is_rate_limited_after_5_attempts(settings):
    settings.RATELIMIT_ENABLE = True
    platform_user = PlatformUserFactory(email=f"{_unique('platform')}@example.test", password="PlatformPass!2026")
    client = APIClient()
    payload = {
        "email": platform_user.email,
        "password": "WrongPlatformPassword!",
        "totp_code": pyotp.TOTP(platform_user.totp_secret).now(),
    }

    responses = [client.post("/api/platform/auth/login/", payload, format="json") for _ in range(6)]

    assert responses[5].status_code == 429
