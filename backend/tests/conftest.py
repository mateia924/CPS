import pytest
from rest_framework.test import APIClient

from apps.access.services import seed_default_roles
from apps.accounting.services import seed_chart_of_accounts, seed_tax_codes_for_country
from apps.organization.services import create_default_legal_entities

from .factories import TenantFactory, UserFactory


@pytest.fixture(autouse=True)
def _disable_ratelimit_by_default(settings):
    # Sprint 4.0: the suite calls /api/auth/login/ and
    # /api/platform/auth/login/ far more than 5 times/minute across many
    # tests. Off by default here; test_rate_limiting.py turns it back on
    # per-test via the same `settings` fixture.
    settings.RATELIMIT_ENABLE = False


@pytest.fixture
def tenant_a(db):
    tenant = TenantFactory(subdomain="tenant-a")
    create_default_legal_entities(tenant, tenant.name)
    seed_chart_of_accounts(tenant)
    # Sprint 4.6: InvoiceLine.tax_code is mandatory — every tenant used
    # by a test needs at least the SA compliance package's codes (S/Z/
    # E/O/RC/SN) available, same as a real tenant gets at registration.
    seed_tax_codes_for_country(tenant, "SA")
    return tenant


@pytest.fixture
def tenant_b(db):
    tenant = TenantFactory(subdomain="tenant-b")
    create_default_legal_entities(tenant, tenant.name)
    seed_chart_of_accounts(tenant)
    seed_tax_codes_for_country(tenant, "SA")
    return tenant


@pytest.fixture
def user_a(tenant_a):
    user = UserFactory(tenant=tenant_a, email="owner@tenant-a.test")
    roles = seed_default_roles(tenant_a)
    user.roles.add(roles["Owner"])
    return user


@pytest.fixture
def user_b(tenant_b):
    user = UserFactory(tenant=tenant_b, email="owner@tenant-b.test")
    roles = seed_default_roles(tenant_b)
    user.roles.add(roles["Owner"])
    return user


@pytest.fixture
def client_a(user_a):
    client = APIClient()
    client.force_authenticate(user=user_a)
    return client


@pytest.fixture
def client_b(user_b):
    client = APIClient()
    client.force_authenticate(user=user_b)
    return client
