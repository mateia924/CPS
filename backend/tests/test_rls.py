"""Sprint 6.6.3 (item 1/4): "الاختبار الحاسم" — a raw ORM query with no
tenant filter, run through a REAL connection as the restricted
`cps_app` role (never the superuser `cps` role pytest's own "default"
alias otherwise connects as — that role bypasses RLS unconditionally,
so it would prove nothing). Connects directly with psycopg rather than
swapping Django's "default" connection, since Django caches a live
connection per alias per thread and pytest's own fixtures already hold
one open on "default" for the surrounding test transaction.
"""

import psycopg
import pytest
from django.conf import settings
from django.db import connection

from apps.common.rls import set_local_tenant_id

from .factories import LegalEntityFactory, PlanFactory, TenantFactory, UserFactory

_INSERT_LEGAL_ENTITY_SQL = (
    "INSERT INTO organization_legalentity "
    "(id, code, name, entity_type, country_code, tax_number, base_currency, is_active, "
    "created_at, tenant_id, tax_period_type, building_number, city, commercial_registration, "
    "district, email, phone, postal_code, short_address, street) "
    "VALUES (gen_random_uuid(), 'X', 'X', 'branch', 'SA', '', 'SAR', true, now(), "
    "%s, 'quarterly', '', '', '', '', '', '', '', '', '')"
)


def _app_role_connection():
    settings_dict = connection.settings_dict
    return psycopg.connect(
        host=settings_dict["HOST"] or "localhost",
        port=settings_dict["PORT"] or 5432,
        dbname=settings_dict["NAME"],
        user=settings.POSTGRES_APP_USER,
        password=settings.POSTGRES_APP_PASSWORD,
    )


@pytest.mark.django_db(transaction=True)
def test_restricted_role_sees_only_the_set_tenants_rows():
    tenant_a = TenantFactory(subdomain="rls-tenant-a")
    tenant_b = TenantFactory(subdomain="rls-tenant-b")
    entity_a = LegalEntityFactory(tenant=tenant_a)
    entity_b = LegalEntityFactory(tenant=tenant_b)

    with _app_role_connection() as conn:
        with conn.cursor() as cur:
            set_local_tenant_id(cur, tenant_a.id)
            cur.execute("SELECT id FROM organization_legalentity")
            rows = {r[0] for r in cur.fetchall()}
        conn.rollback()  # never actually commit as this role — read-only check
    assert entity_a.id in rows
    assert entity_b.id not in rows


@pytest.mark.django_db(transaction=True)
def test_restricted_role_sees_nothing_with_no_tenant_context_set():
    tenant_a = TenantFactory(subdomain="rls-tenant-c")
    entity_a = LegalEntityFactory(tenant=tenant_a)

    with _app_role_connection() as conn:
        with conn.cursor() as cur:
            # No SET LOCAL at all — the exact "outside any request"
            # case the spec names explicitly.
            cur.execute("SELECT id FROM organization_legalentity")
            rows = {r[0] for r in cur.fetchall()}
        conn.rollback()
    assert entity_a.id not in rows
    assert rows == set()


@pytest.mark.django_db
def test_restricted_role_cannot_insert_a_row_for_a_different_tenant():
    """The same policy doubles as the WITH CHECK clause for writes —
    not just SELECT is protected."""
    tenant_a = TenantFactory(subdomain="rls-tenant-d")
    tenant_b = TenantFactory(subdomain="rls-tenant-e")

    with _app_role_connection() as conn:
        with conn.cursor() as cur:
            set_local_tenant_id(cur, tenant_a.id)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute(_INSERT_LEGAL_ENTITY_SQL, [str(tenant_b.id)])
        conn.rollback()


@pytest.mark.django_db
def test_restricted_role_can_insert_a_row_for_its_own_set_tenant():
    tenant_a = TenantFactory(subdomain="rls-tenant-f")

    with _app_role_connection() as conn:
        with conn.cursor() as cur:
            set_local_tenant_id(cur, tenant_a.id)
            cur.execute(_INSERT_LEGAL_ENTITY_SQL + " RETURNING id", [str(tenant_a.id)])
            assert cur.fetchone() is not None
        conn.rollback()  # never actually persisted either way


@pytest.mark.django_db(transaction=True)
def test_registration_under_the_restricted_role_creates_a_fully_usable_tenant(settings):
    """Sprint 6.6.3 (item 1): the one write path with no authenticated
    tenant request yet to have set `cps.tenant_id` already — proves
    RegisterSerializer.create()'s own mid-transaction SET LOCAL (right
    after the Tenant row itself, which carries no tenant_id and so is
    never RLS-restricted in the first place) actually lets every
    following INSERT (User, TenantFeatures, LegalEntity, Role,
    ApprovalRule...) through under the SAME restricted role, using a
    real end-to-end HTTP registration. Checks the written rows
    directly via a fresh `cps_app` connection afterward, rather than a
    second HTTP request on the same swapped connection — Django's
    connection-pooling-by-thread makes chaining a second request onto
    a mid-test connection swap unreliable."""
    from django.test import Client as DjangoTestClient

    # Sprint 6.6.3: not relying on migration-seeded Plan rows surviving
    # here — an earlier transaction=True test in this same file/session
    # may already have truncated them (each such test flushes every
    # table on teardown, with no guaranteed reseed order across the
    # rest of the suite); get_or_create recreates it if missing.
    PlanFactory(code="free")
    original = settings.DATABASES["default"].copy()
    settings.DATABASES["default"]["USER"] = settings.POSTGRES_APP_USER
    settings.DATABASES["default"]["PASSWORD"] = settings.POSTGRES_APP_PASSWORD
    connection.close()
    connection.settings_dict.update(settings.DATABASES["default"])
    try:
        client = DjangoTestClient()
        response = client.post(
            "/api/auth/register/",
            {
                "company_name": "RLS Registration Test", "subdomain": "rls-registration-test",
                "email": "owner@rls-registration-test.test", "password": "RlsRegTest!2026",
            },
            content_type="application/json",
        )
        assert response.status_code == 201, response.json()
        tenant_id = response.json()["tenant"]["id"]
    finally:
        connection.close()
        connection.settings_dict.update(original)

    with _app_role_connection() as conn:
        with conn.cursor() as cur:
            set_local_tenant_id(cur, tenant_id)
            cur.execute("SELECT count(*) FROM accounts_user WHERE tenant_id = %s", [tenant_id])
            assert cur.fetchone()[0] == 1
            cur.execute("SELECT count(*) FROM tenants_tenantfeatures WHERE tenant_id = %s", [tenant_id])
            assert cur.fetchone()[0] == 1
            cur.execute("SELECT count(*) FROM organization_legalentity WHERE tenant_id = %s", [tenant_id])
            assert cur.fetchone()[0] >= 1
            cur.execute("SELECT count(*) FROM access_role WHERE tenant_id = %s", [tenant_id])
            assert cur.fetchone()[0] >= 1
        conn.rollback()


@pytest.mark.django_db(transaction=True)
def test_login_under_the_restricted_role_for_a_pre_existing_user(settings):
    """Sprint 6.6.3 (item 1): found live, the hard way — the FIRST fix
    to TenantLoginSerializer.validate() only set `cps.tenant_id` AFTER
    authenticate() returned, for the AuditLog write alone. But apps.
    accounts.backends.TenantEmailBackend's own credential check is
    itself `User.objects.get(tenant=tenant, email__iexact=email)` — a
    SELECT on accounts_user, RLS-protected — called *during*
    authenticate(), before that fix ever ran. Under the restricted
    role, that SELECT silently matched zero rows regardless of the
    password, so EVERY login failed with "wrong credentials" — this
    reproduces exactly that (a user created independently of any
    registration flow, logging in for real over HTTP) so the fix
    (`cps.tenant_id` set from the subdomain alone, before authenticate()
    is ever called) can never silently regress."""
    tenant = TenantFactory(subdomain="rls-login-test")
    UserFactory(tenant=tenant, email="owner@rls-login-test.test", password="RlsLoginTest!2026")

    from django.test import Client as DjangoTestClient

    original = settings.DATABASES["default"].copy()
    settings.DATABASES["default"]["USER"] = settings.POSTGRES_APP_USER
    settings.DATABASES["default"]["PASSWORD"] = settings.POSTGRES_APP_PASSWORD
    connection.close()
    connection.settings_dict.update(settings.DATABASES["default"])
    try:
        client = DjangoTestClient()
        response = client.post(
            "/api/auth/login/",
            {"subdomain": "rls-login-test", "email": "owner@rls-login-test.test", "password": "RlsLoginTest!2026"},
            content_type="application/json",
        )
        assert response.status_code == 200, response.json()

        # Sprint 6.6.3 (item 1) — a SECOND, separate live bug: every
        # *subsequent* authenticated request goes through apps.tenants.
        # middleware.RLSTenantMiddleware too, and its own FIRST version
        # called TenantAwareJWTAuthentication.authenticate() in full to
        # learn `tenant_id` — whose own get_user() is itself a SELECT
        # on accounts_user, with no `cps.tenant_id` set yet (that's
        # what this call was trying to determine in the first place).
        # Fixed by reading `tenant_id` directly off the access token's
        # own claims (a pure, DB-free claims decode) instead. /auth/me/
        # is the simplest such request — this would have caught it.
        me = client.get("/api/auth/me/", HTTP_AUTHORIZATION=f"Bearer {response.json()['access']}")
        assert me.status_code == 200, me.json()

        # Sprint 6.6.3 (item 1) — a THIRD, separate live bug: simplejwt's
        # own stock TokenRefreshView carries its token in the POST body,
        # not the Authorization header the middleware otherwise reads —
        # its TokenRefreshSerializer.validate() does its own SELECT on
        # accounts_user too. Fixed by falling back to decoding the
        # refresh token straight out of the request body for this one
        # path.
        refresh = client.post(
            "/api/auth/refresh/", {"refresh": response.json()["refresh"]}, content_type="application/json",
        )
        assert refresh.status_code == 200, refresh.json()
    finally:
        connection.close()
        connection.settings_dict.update(original)
