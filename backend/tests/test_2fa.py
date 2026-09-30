"""Sprint 6.6.2 (item 5): 2FA (TOTP) at login. Uses a real bearer token
(client.credentials(HTTP_AUTHORIZATION=...)) rather than
force_authenticate — the same real-HTTP shape test_tenant_subdomain_
rules.py already uses for the platform side — since
apps.accounts.middleware.MustChangePasswordMiddleware (exercised by
test_must_change_password.py) only ever sees a real Authorization
header, never force_authenticate's bypass."""

import pyotp
import pytest
from rest_framework.test import APIClient

from .factories import UserFactory

PASSWORD = "TestPass!2026"


def _login(subdomain, email, password, totp_code=None):
    client = APIClient()
    payload = {"subdomain": subdomain, "email": email, "password": password}
    if totp_code is not None:
        payload["totp_code"] = totp_code
    return client.post("/api/auth/login/", payload, format="json")


@pytest.mark.django_db
def test_login_without_code_is_rejected_with_arabic_message_when_2fa_confirmed(tenant_a, user_a):
    user_a.totp_secret = pyotp.random_base32()
    user_a.totp_confirmed = True
    user_a.save(update_fields=["totp_secret", "totp_confirmed"])

    response = _login(tenant_a.subdomain, user_a.email, PASSWORD)
    assert response.status_code == 403, response.data
    assert "detail" in response.data


@pytest.mark.django_db
def test_login_with_correct_code_issues_a_jwt(tenant_a, user_a):
    secret = pyotp.random_base32()
    user_a.totp_secret = secret
    user_a.totp_confirmed = True
    user_a.save(update_fields=["totp_secret", "totp_confirmed"])

    response = _login(tenant_a.subdomain, user_a.email, PASSWORD, totp_code=pyotp.TOTP(secret).now())
    assert response.status_code == 200, response.data
    assert response.data["access"]
    assert response.data["refresh"]


@pytest.mark.django_db
def test_login_with_wrong_code_is_rejected(tenant_a, user_a):
    user_a.totp_secret = pyotp.random_base32()
    user_a.totp_confirmed = True
    user_a.save(update_fields=["totp_secret", "totp_confirmed"])

    response = _login(tenant_a.subdomain, user_a.email, PASSWORD, totp_code="000000")
    assert response.status_code == 403, response.data


@pytest.mark.django_db
def test_login_not_yet_enrolled_but_required_by_role_flags_setup_without_blocking(tenant_a, user_a):
    # require_2fa_for_roles defaults to [] (off) — "عند التفعيل" in the
    # spec means this only ever applies once the Owner actively turns
    # it on from Settings, never silently for every brand-new tenant
    # (a non-empty default would force every fresh registration
    # straight into the 2FA setup screen before seeing anything else).
    assert tenant_a.require_2fa_for_roles == []
    tenant_a.require_2fa_for_roles = ["Owner"]
    tenant_a.save(update_fields=["require_2fa_for_roles"])

    # user_a holds the Owner role — enrollment is now REQUIRED but
    # user_a hasn't set it up yet: login must still succeed (no code
    # asked for), only flagged so the frontend forces the setup screen.
    response = _login(tenant_a.subdomain, user_a.email, PASSWORD)
    assert response.status_code == 200, response.data
    assert response.data["requires_2fa_setup"] is True


@pytest.mark.django_db
def test_setup_confirm_and_disable_round_trip(tenant_a, user_a):
    client = APIClient()
    login = _login(tenant_a.subdomain, user_a.email, PASSWORD)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

    setup = client.post("/api/auth/2fa/setup/")
    assert setup.status_code == 200, setup.data
    secret = setup.data["secret"]
    assert setup.data["qr_code"].startswith("data:image/svg+xml;base64,")

    bad_confirm = client.post("/api/auth/2fa/confirm/", {"code": "000000"}, format="json")
    assert bad_confirm.status_code == 400

    confirm = client.post("/api/auth/2fa/confirm/", {"code": pyotp.TOTP(secret).now()}, format="json")
    assert confirm.status_code == 200, confirm.data
    assert len(confirm.data["backup_codes"]) == 10

    user_a.refresh_from_db()
    assert user_a.totp_confirmed is True

    # Now login requires a code — a backup code works exactly once.
    locked_out = _login(tenant_a.subdomain, user_a.email, PASSWORD)
    assert locked_out.status_code == 403
    first_use = _login(tenant_a.subdomain, user_a.email, PASSWORD, totp_code=confirm.data["backup_codes"][0])
    assert first_use.status_code == 200, first_use.data
    second_use = _login(tenant_a.subdomain, user_a.email, PASSWORD, totp_code=confirm.data["backup_codes"][0])
    assert second_use.status_code == 403

    disable_wrong_password = client.post("/api/auth/2fa/disable/", {"password": "wrong"}, format="json")
    assert disable_wrong_password.status_code == 400
    disable = client.post("/api/auth/2fa/disable/", {"password": PASSWORD}, format="json")
    assert disable.status_code == 204
    user_a.refresh_from_db()
    assert user_a.totp_confirmed is False

    # Disabled — login no longer asks for a code.
    after_disable = _login(tenant_a.subdomain, user_a.email, PASSWORD)
    assert after_disable.status_code == 200


@pytest.mark.django_db
def test_voluntary_2fa_gates_login_even_without_a_role_requirement(tenant_a):
    # A role NOT in require_2fa_for_roles can still opt in from their
    # own profile — totp_confirmed alone is what gates login (item 1:
    # "تفعيل اختياري من ملفي الشخصي").
    tenant_a.require_2fa_for_roles = []
    tenant_a.save(update_fields=["require_2fa_for_roles"])
    staff = UserFactory(tenant=tenant_a, email="staff@tenant-a.test", password=PASSWORD)
    secret = pyotp.random_base32()
    staff.totp_secret = secret
    staff.totp_confirmed = True
    staff.save(update_fields=["totp_secret", "totp_confirmed"])

    without_code = _login(tenant_a.subdomain, staff.email, PASSWORD)
    assert without_code.status_code == 403
    with_code = _login(tenant_a.subdomain, staff.email, PASSWORD, totp_code=pyotp.TOTP(secret).now())
    assert with_code.status_code == 200
