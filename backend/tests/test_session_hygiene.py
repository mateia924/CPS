"""Sprint 6.6.2 (item 5): "تعطيل مستخدم يُبطل refresh" + item 4's
"الجلسات النشطة"/"تسجيل الخروج من كل الأجهزة"."""

import pytest
from rest_framework.test import APIClient

from .factories import UserFactory

PASSWORD = "TestPass!2026"


def _login(tenant, email, password=PASSWORD):
    client = APIClient()
    login = client.post(
        "/api/auth/login/", {"subdomain": tenant.subdomain, "email": email, "password": password},
        format="json",
    )
    assert login.status_code == 200, login.data
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    return client, login.data


@pytest.mark.django_db
def test_deactivating_a_user_invalidates_their_refresh_token(tenant_a, client_a):
    staff = UserFactory(tenant=tenant_a, email="staff@tenant-a.test", password=PASSWORD)
    _client, login_data = _login(tenant_a, staff.email)

    deactivate = client_a.post(f"/api/users/{staff.id}/deactivate/")
    assert deactivate.status_code == 200, deactivate.data

    refresh_attempt = APIClient().post(
        "/api/auth/refresh/", {"refresh": login_data["refresh"]}, format="json"
    )
    assert refresh_attempt.status_code == 401, refresh_attempt.data


@pytest.mark.django_db
def test_active_sessions_list_and_logout_all_devices(tenant_a):
    staff = UserFactory(tenant=tenant_a, email="staff2@tenant-a.test", password=PASSWORD)
    client_1, login_1 = _login(tenant_a, staff.email)
    client_2, login_2 = _login(tenant_a, staff.email)

    sessions = client_1.get("/api/auth/sessions/")
    assert sessions.status_code == 200, sessions.data
    assert len(sessions.data) == 2

    logout_all = client_1.post("/api/auth/logout-all/")
    assert logout_all.status_code == 204

    for refresh in (login_1["refresh"], login_2["refresh"]):
        attempt = APIClient().post("/api/auth/refresh/", {"refresh": refresh}, format="json")
        assert attempt.status_code == 401
