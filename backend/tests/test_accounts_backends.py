"""Sprint 4.0 (ARCH_REVIEW_1.md debt #8): apps/accounts/backends.py is
the same file that caused the critical cross-tenant auth bypass fixed
before sprint 0 closed (see the module docstring there and README).
The one path it still had zero coverage on is exactly the most
sensitive one: the subdomain-less fallback meant only for platform
superusers logging into Django /admin/.
"""

import pytest
from django.contrib.auth import authenticate

from .factories import TenantFactory, UserFactory

PASSWORD = "TestPass!2026"


@pytest.mark.django_db(databases=["default", "platform"], transaction=True)
def test_subdomainless_login_succeeds_for_superuser():
    tenant = TenantFactory(subdomain="backend-t1")
    superuser = UserFactory(
        tenant=tenant, email="root@backend-t1.test", password=PASSWORD, is_superuser=True
    )

    user = authenticate(email=superuser.email, password=PASSWORD)

    assert user == superuser


@pytest.mark.django_db(databases=["default", "platform"], transaction=True)
def test_subdomainless_login_rejects_non_superuser_regardless_of_tenant():
    tenant = TenantFactory(subdomain="backend-t2")
    UserFactory(tenant=tenant, email="regular@backend-t2.test", password=PASSWORD, is_superuser=False)

    user = authenticate(email="regular@backend-t2.test", password=PASSWORD)

    assert user is None


@pytest.mark.django_db(databases=["default", "platform"], transaction=True)
def test_subdomainless_login_rejects_disabled_superuser():
    tenant = TenantFactory(subdomain="backend-t3")
    UserFactory(
        tenant=tenant,
        email="disabled-root@backend-t3.test",
        password=PASSWORD,
        is_superuser=True,
        is_active=False,
    )

    user = authenticate(email="disabled-root@backend-t3.test", password=PASSWORD)

    assert user is None


@pytest.mark.django_db(databases=["default", "platform"], transaction=True)
def test_subdomainless_login_rejects_wrong_password_for_superuser():
    tenant = TenantFactory(subdomain="backend-t4")
    UserFactory(tenant=tenant, email="root2@backend-t4.test", password=PASSWORD, is_superuser=True)

    user = authenticate(email="root2@backend-t4.test", password="WrongPass!2026")

    assert user is None


@pytest.mark.django_db(databases=["default", "platform"], transaction=True)
def test_subdomainless_login_rejects_email_shared_by_two_superusers():
    # authenticate() must not guess which account was meant when the
    # (intentionally unenforced-at-DB-level) "globally unique by
    # convention" assumption on superuser email is violated — the
    # backend requires exactly one candidate.
    tenant_x = TenantFactory(subdomain="backend-t5x")
    tenant_y = TenantFactory(subdomain="backend-t5y")
    UserFactory(tenant=tenant_x, email="dup-root@shared.test", password=PASSWORD, is_superuser=True)
    UserFactory(tenant=tenant_y, email="dup-root@shared.test", password=PASSWORD, is_superuser=True)

    user = authenticate(email="dup-root@shared.test", password=PASSWORD)

    assert user is None


@pytest.mark.django_db
def test_login_with_subdomain_ignores_superuser_shortcut():
    # Sanity check: passing a subdomain always goes through the
    # (tenant, email) lookup, never the superuser fallback, even for a
    # superuser account.
    tenant = TenantFactory(subdomain="backend-t6")
    UserFactory(tenant=tenant, email="root3@backend-t6.test", password=PASSWORD, is_superuser=True)

    user = authenticate(subdomain="backend-t6", email="root3@backend-t6.test", password=PASSWORD)

    assert user is not None
    assert user.email == "root3@backend-t6.test"
