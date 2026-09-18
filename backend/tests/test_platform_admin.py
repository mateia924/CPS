"""Sprint 2 (docs/SYSTEM_ANALYSIS.md 3.14): platform admin, plans, and
the audit log. Covers every explicit test scenario from the sprint 2
spec section 6.

Unlike most of this suite, several tests here deliberately do NOT use
client_a/client_b's force_authenticate — that bypasses the
authentication_classes machinery entirely, which is exactly what's
under test (a real customer JWT vs a real platform JWT, and the
TenantAwareJWTAuthentication status checks). Those tests log in for
real via /api/auth/login/ or /api/platform/auth/login/ instead.
"""

import pyotp
import pytest
from django.db import DatabaseError, transaction
from rest_framework.test import APIClient

from apps.access.services import seed_default_roles
from apps.accounting.services import seed_chart_of_accounts
from apps.organization.services import create_default_legal_entities
from apps.platform.models import AuditLog, Plan, PlatformBackupCode
from apps.platform.services import generate_backup_codes
from apps.tenants.models import Tenant
from apps.tenants.services import apply_plan_to_tenant

from .factories import PlanFactory, PlatformUserFactory, TenantFactory, UserFactory

CUSTOMER_PASSWORD = "TestPass!2026"


def _platform_login(client, user, code=None, password="PlatformPass!2026"):
    return client.post(
        "/api/platform/auth/login/",
        {
            "email": user.email,
            "password": password,
            "totp_code": code if code is not None else pyotp.TOTP(user.totp_secret).now(),
        },
        format="json",
    )


@pytest.fixture
def platform_user(db):
    return PlatformUserFactory(password="PlatformPass!2026")


@pytest.fixture
def platform_client(platform_user):
    client = APIClient()
    response = _platform_login(client, platform_user)
    assert response.status_code == 200
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
    return client


@pytest.fixture
def tenant_with_owner(db):
    tenant = TenantFactory(subdomain="platform-t1")
    apply_plan_to_tenant(tenant, tenant.plan)
    create_default_legal_entities(tenant, tenant.name)
    seed_chart_of_accounts(tenant)
    roles = seed_default_roles(tenant)
    owner = UserFactory(tenant=tenant, email="owner@platform-t1.test", password=CUSTOMER_PASSWORD)
    owner.roles.add(roles["Owner"])
    return tenant, owner


def _customer_login(client, tenant, user):
    return client.post(
        "/api/auth/login/",
        {"subdomain": tenant.subdomain, "email": user.email, "password": CUSTOMER_PASSWORD},
        format="json",
    )


# ---------------------------------------------------------------------
# 2FA
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_platform_login_without_code_is_rejected(platform_user):
    client = APIClient()
    response = client.post(
        "/api/platform/auth/login/",
        {"email": platform_user.email, "password": "PlatformPass!2026"},
        format="json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_platform_login_with_correct_code_succeeds(platform_user):
    client = APIClient()
    response = _platform_login(client, platform_user)
    assert response.status_code == 200
    assert "access" in response.data
    assert response.data["user"]["email"] == platform_user.email


@pytest.mark.django_db
def test_platform_login_with_wrong_code_is_rejected(platform_user):
    client = APIClient()
    response = _platform_login(client, platform_user, code="000000")
    assert response.status_code == 401


@pytest.mark.django_db
def test_backup_code_can_be_used_exactly_once(platform_user):
    codes = generate_backup_codes(platform_user)
    client = APIClient()

    first = _platform_login(client, platform_user, code=codes[0])
    assert first.status_code == 200

    second = _platform_login(client, platform_user, code=codes[0])
    assert second.status_code == 401

    used = PlatformBackupCode.objects.get(
        user=platform_user, code_hash=PlatformBackupCode.hash_code(codes[0])
    )
    assert used.used_at is not None


# ---------------------------------------------------------------------
# Token isolation: a platform token and a customer token belong to
# completely disjoint auth realms with different signing keys.
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_platform_token_rejected_on_customer_path(platform_client):
    response = platform_client.get("/api/customers/")
    assert response.status_code == 401


@pytest.mark.django_db
def test_customer_token_rejected_on_platform_path_returns_404(tenant_with_owner):
    tenant, owner = tenant_with_owner
    client = APIClient()
    login = _customer_login(client, tenant, owner)
    assert login.status_code == 200
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

    response = client.get("/api/platform/tenants/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_unauthenticated_request_to_platform_path_returns_404(db):
    response = APIClient().get("/api/platform/tenants/")
    assert response.status_code == 404


# ---------------------------------------------------------------------
# Plans / limits
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_change_plan_updates_tenant_features_immediately(tenant_with_owner, platform_client):
    tenant, _owner = tenant_with_owner
    free_plan = Plan.objects.get(code="free")
    apply_plan_to_tenant(tenant, free_plan)
    tenant.features.refresh_from_db()
    assert tenant.features.inventory is False

    business = Plan.objects.get(code="business")
    response = platform_client.post(f"/api/platform/tenants/{tenant.id}/change_plan/", {"plan": business.id})
    assert response.status_code == 200

    tenant.refresh_from_db()
    assert tenant.plan_id == business.id
    tenant.features.refresh_from_db()
    assert tenant.features.inventory is True
    assert tenant.features.cost_centers is True


@pytest.mark.django_db
def test_exceeding_max_users_returns_402(db):
    limited_plan = PlanFactory(code="limited-users-test", max_users=1)
    tenant = TenantFactory(subdomain="limited-users", plan=limited_plan)
    roles = seed_default_roles(tenant)
    owner = UserFactory(tenant=tenant, email="owner@limited-users.test")
    owner.roles.add(roles["Owner"])

    client = APIClient()
    client.force_authenticate(user=owner)

    response = client.post(
        "/api/users/",
        {"email": "second@limited-users.test", "password": "AnotherPass!2026"},
        format="json",
    )
    assert response.status_code == 402


@pytest.mark.django_db
def test_below_max_users_succeeds(db):
    roomy_plan = PlanFactory(code="roomy-users-test", max_users=5)
    tenant = TenantFactory(subdomain="roomy-users", plan=roomy_plan)
    roles = seed_default_roles(tenant)
    owner = UserFactory(tenant=tenant, email="owner@roomy-users.test")
    owner.roles.add(roles["Owner"])

    client = APIClient()
    client.force_authenticate(user=owner)

    response = client.post(
        "/api/users/",
        {"email": "second@roomy-users.test", "password": "AnotherPass!2026"},
        format="json",
    )
    assert response.status_code == 201


# ---------------------------------------------------------------------
# Tenant status: SUSPENDED (read-only, 403 on write) / ARCHIVED (401)
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_suspended_tenant_allows_read_but_blocks_write(tenant_with_owner):
    tenant, owner = tenant_with_owner
    client = APIClient()
    login = _customer_login(client, tenant, owner)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

    tenant.status = Tenant.Status.SUSPENDED
    tenant.save(update_fields=["status"])

    get_response = client.get("/api/customers/")
    assert get_response.status_code == 200

    post_response = client.post("/api/customers/", {"name": "Blocked"}, format="json")
    assert post_response.status_code == 403


@pytest.mark.django_db
def test_archived_tenant_blocks_all_access(tenant_with_owner):
    tenant, owner = tenant_with_owner
    client = APIClient()
    login = _customer_login(client, tenant, owner)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

    tenant.status = Tenant.Status.ARCHIVED
    tenant.save(update_fields=["status"])

    response = client.get("/api/customers/")
    assert response.status_code == 401


@pytest.mark.django_db
def test_suspend_and_activate_require_a_reason(tenant_with_owner, platform_client):
    tenant, _owner = tenant_with_owner

    missing_reason = platform_client.post(f"/api/platform/tenants/{tenant.id}/suspend/", {})
    assert missing_reason.status_code == 400

    response = platform_client.post(
        f"/api/platform/tenants/{tenant.id}/suspend/", {"reason": "non-payment"}
    )
    assert response.status_code == 200
    tenant.refresh_from_db()
    assert tenant.status == Tenant.Status.SUSPENDED

    response = platform_client.post(
        f"/api/platform/tenants/{tenant.id}/activate/", {"reason": "payment received"}
    )
    assert response.status_code == 200
    tenant.refresh_from_db()
    assert tenant.status == Tenant.Status.ACTIVE


# ---------------------------------------------------------------------
# Audit log: created on admin actions, immutable both at the DRF layer
# and at the database layer.
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_admin_action_creates_audit_log_entry(tenant_with_owner, platform_client, platform_user):
    tenant, _owner = tenant_with_owner
    platform_client.post(
        f"/api/platform/tenants/{tenant.id}/suspend/", {"reason": "audit test"}
    )
    entry = AuditLog.objects.filter(tenant_id=tenant.id, action="tenant.suspend").first()
    assert entry is not None
    assert entry.actor_id == platform_user.id
    assert entry.actor_type == AuditLog.ActorType.PLATFORM


@pytest.mark.django_db
def test_login_creates_audit_log_entries_for_success_and_failure(tenant_with_owner):
    tenant, owner = tenant_with_owner
    client = APIClient()

    client.post(
        "/api/auth/login/",
        {"subdomain": tenant.subdomain, "email": owner.email, "password": "wrong-password"},
        format="json",
    )
    assert AuditLog.objects.filter(
        tenant_id=tenant.id, action="tenant_user.login_failed"
    ).exists()

    _customer_login(client, tenant, owner)
    assert AuditLog.objects.filter(tenant_id=tenant.id, action="tenant_user.login").exists()


@pytest.mark.django_db
def test_audit_log_rejects_update_and_delete_via_api(platform_client):
    entry = AuditLog.objects.create(
        actor_type=AuditLog.ActorType.PLATFORM, actor_id=None, action="seed.entry"
    )

    patch_response = platform_client.patch(f"/api/platform/audit-log/{entry.id}/", {"action": "x"})
    assert patch_response.status_code == 405

    delete_response = platform_client.delete(f"/api/platform/audit-log/{entry.id}/")
    assert delete_response.status_code == 405


@pytest.mark.django_db
def test_audit_log_is_immutable_at_the_database_level(db):
    entry = AuditLog.objects.create(
        actor_type=AuditLog.ActorType.PLATFORM, actor_id=None, action="db-immutability-test"
    )

    with pytest.raises(DatabaseError):
        with transaction.atomic():
            AuditLog.objects.filter(pk=entry.pk).update(action="hacked")

    with pytest.raises(DatabaseError):
        with transaction.atomic():
            AuditLog.objects.filter(pk=entry.pk).delete()

    entry.refresh_from_db()
    assert entry.action == "db-immutability-test"


# ---------------------------------------------------------------------
# Isolation: SUPPORT sees every tenant (by design); a tenant user
# cannot reach any /api/platform/ path (covered above, 404).
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_support_role_sees_all_tenants(db):
    from apps.platform.models import PlatformUser

    tenant_x = TenantFactory(subdomain="support-visible-x")
    tenant_y = TenantFactory(subdomain="support-visible-y")

    support_user = PlatformUserFactory(
        password="SupportPass!2026", role=PlatformUser.Role.SUPPORT
    )
    client = APIClient()
    login = _platform_login(client, support_user, password="SupportPass!2026")
    assert login.status_code == 200
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

    response = client.get("/api/platform/tenants/")
    assert response.status_code == 200
    subdomains = {t["subdomain"] for t in response.data["results"]}
    assert {tenant_x.subdomain, tenant_y.subdomain} <= subdomains
