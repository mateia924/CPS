"""Sprint 6.6.2 (item 5): a temporary password reaches only the
change-password screen — apps.accounts.middleware.
MustChangePasswordMiddleware blocks everything else. Uses a real
bearer token (see test_2fa.py's own module docstring for why)."""

import pytest
from rest_framework.test import APIClient

from apps.access.services import seed_default_roles

from .factories import UserFactory

PASSWORD = "TempPass!2026"
NEW_PASSWORD = "BrandNewPass!2026"


def _client_as(tenant, email, password):
    client = APIClient()
    login = client.post(
        "/api/auth/login/", {"subdomain": tenant.subdomain, "email": email, "password": password},
        format="json",
    )
    assert login.status_code == 200, login.data
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    return client, login.data


@pytest.mark.django_db
def test_must_change_password_user_is_blocked_everywhere_except_the_change_screen(tenant_a):
    user = UserFactory(tenant=tenant_a, email="temp@tenant-a.test", password=PASSWORD)
    user.roles.add(seed_default_roles(tenant_a)["Owner"])
    user.must_change_password = True
    user.save(update_fields=["must_change_password"])

    client, login_data = _client_as(tenant_a, user.email, PASSWORD)
    assert login_data["must_change_password"] is True

    blocked = client.get("/api/invoices/")
    assert blocked.status_code == 403
    # A plain JsonResponse from middleware, not a DRF Response — no
    # `.data` attribute. Arabic, not a stock DRF permission_denied string.
    assert "تغيير كلمة السر" in blocked.json()["detail"]

    # /me/ stays reachable (read-only status) — never trapped blind.
    me = client.get("/api/auth/me/")
    assert me.status_code == 200, me.data

    refresh_token = login_data["refresh"]
    change = client.post(
        "/api/auth/change-password/",
        {"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        format="json",
    )
    assert change.status_code == 204, change.data
    user.refresh_from_db()
    assert user.must_change_password is False

    # "انتهاء refresh token عند تغيير كلمة السر" — the short-lived
    # access token already in hand keeps working for its remaining
    # natural lifetime (no per-request blacklist check on access
    # tokens, only on refresh — same as simplejwt's own BLACKLIST_
    # AFTER_ROTATION design elsewhere in this project), but the refresh
    # token can never mint another one.
    refresh_attempt = APIClient().post("/api/auth/refresh/", {"refresh": refresh_token}, format="json")
    assert refresh_attempt.status_code == 401, refresh_attempt.data

    # The negative half of this same round trip (2026-10-05 incident
    # review, point 3): this forced-change screen is our ONLY password
    # recovery mechanism today (no self-service "forgot password" path
    # exists anywhere in the code), so it had zero coverage proving the
    # OLD temporary password actually stops working once changed — a
    # gap that would have let a leaked/observed temp password (exactly
    # what this project printed in plaintext chat earlier tonight) keep
    # working indefinitely after the real user moved on.
    old_password_login = APIClient().post(
        "/api/auth/login/",
        {"subdomain": tenant_a.subdomain, "email": user.email, "password": PASSWORD},
        format="json",
    )
    # TenantLoginSerializer.validate() raises a plain ValidationError for
    # bad credentials (DRF maps that to 400) — not 401, which is only
    # /api/auth/refresh/'s own convention for a dead refresh token above.
    assert old_password_login.status_code == 400, old_password_login.data

    fresh_client, fresh_login = _client_as(tenant_a, user.email, NEW_PASSWORD)
    assert fresh_login["must_change_password"] is False
    assert fresh_client.get("/api/invoices/").status_code == 200


@pytest.mark.django_db
def test_admin_reset_password_forces_must_change_password(tenant_a, client_a):
    created = client_a.post(
        "/api/users/", {"email": "newstaff@tenant-a.test", "password": "InitialPass!2026"}, format="json",
    )
    assert created.status_code == 201
    assert created.data["must_change_password"] is True

    reset = client_a.post(
        f"/api/users/{created.data['id']}/reset_password/", {"new_password": "ResetPass!2026"}, format="json",
    )
    assert reset.status_code == 200, reset.data
    assert reset.data["must_change_password"] is True

    client, login_data = _client_as(tenant_a, "newstaff@tenant-a.test", "ResetPass!2026")
    assert login_data["must_change_password"] is True
    assert client.get("/api/invoices/").status_code == 403
