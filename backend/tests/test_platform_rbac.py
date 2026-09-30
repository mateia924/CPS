"""Sprint 6.6.2 (item 5): "support لا يستطيع الكتابة" — functional
proof on top of test_platform_rbac_structural.py's structural check."""

import pyotp
import pytest
from rest_framework.test import APIClient

from apps.platform.models import PlatformUser
from apps.tenants.models import Tenant

from .factories import PlanFactory, PlatformUserFactory, TenantFactory


def _login(platform_user, password="TestPass!2026"):
    client = APIClient()
    login = client.post(
        "/api/platform/auth/login/",
        {
            "email": platform_user.email, "password": password,
            "totp_code": pyotp.TOTP(platform_user.totp_secret).now(),
        },
        format="json",
    )
    assert login.status_code == 200, login.data
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    return client


@pytest.mark.django_db(databases=["default", "platform"], transaction=True)
def test_support_can_read_but_not_change_plan_or_extend_trial():
    support = PlatformUserFactory(role=PlatformUser.Role.SUPPORT)
    tenant = TenantFactory(plan=PlanFactory(code="free-rbac-test"))
    client = _login(support)

    listed = client.get("/api/platform/tenants/")
    assert listed.status_code == 200, listed.data

    other_plan = PlanFactory(code="enterprise-rbac-test")
    change_plan = client.post(f"/api/platform/tenants/{tenant.id}/change_plan/", {"plan": other_plan.id}, format="json")
    assert change_plan.status_code == 403, change_plan.data

    extend = client.post(
        f"/api/platform/tenants/{tenant.id}/extend_trial/", {"trial_ends_at": "2027-01-01T00:00:00Z"}, format="json",
    )
    assert extend.status_code == 403, extend.data


@pytest.mark.django_db(databases=["default", "platform"], transaction=True)
def test_support_can_suspend_a_tenant_with_a_reason():
    support = PlatformUserFactory(role=PlatformUser.Role.SUPPORT)
    tenant = TenantFactory(plan=PlanFactory(code="free-rbac-test-2"), status=Tenant.Status.ACTIVE)
    client = _login(support)

    suspend = client.post(f"/api/platform/tenants/{tenant.id}/suspend/", {"reason": "non-payment"}, format="json")
    assert suspend.status_code == 200, suspend.data
    tenant.refresh_from_db()
    assert tenant.status == Tenant.Status.SUSPENDED


@pytest.mark.django_db(databases=["default", "platform"], transaction=True)
def test_billing_can_change_plan_but_not_suspend():
    billing = PlatformUserFactory(role=PlatformUser.Role.BILLING)
    tenant = TenantFactory(plan=PlanFactory(code="free-rbac-test-3"), status=Tenant.Status.ACTIVE)
    client = _login(billing)

    new_plan = PlanFactory(code="enterprise-rbac-test-3")
    change_plan = client.post(f"/api/platform/tenants/{tenant.id}/change_plan/", {"plan": new_plan.id}, format="json")
    assert change_plan.status_code == 200, change_plan.data

    suspend = client.post(f"/api/platform/tenants/{tenant.id}/suspend/", {"reason": "test-reason"}, format="json")
    assert suspend.status_code == 403, suspend.data


@pytest.mark.django_db(databases=["default", "platform"], transaction=True)
def test_super_admin_can_do_everything():
    admin = PlatformUserFactory(role=PlatformUser.Role.SUPER_ADMIN)
    tenant = TenantFactory(plan=PlanFactory(code="free-rbac-test-4"), status=Tenant.Status.ACTIVE)
    client = _login(admin)

    new_plan = PlanFactory(code="enterprise-rbac-test-4")
    assert client.post(f"/api/platform/tenants/{tenant.id}/change_plan/", {"plan": new_plan.id}, format="json").status_code == 200
    assert client.post(f"/api/platform/tenants/{tenant.id}/suspend/", {"reason": "test-reason"}, format="json").status_code == 200
