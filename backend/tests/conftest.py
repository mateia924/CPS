import pytest
from rest_framework.test import APIClient

from .factories import TenantFactory, UserFactory


@pytest.fixture
def tenant_a(db):
    return TenantFactory(subdomain="tenant-a")


@pytest.fixture
def tenant_b(db):
    return TenantFactory(subdomain="tenant-b")


@pytest.fixture
def user_a(tenant_a):
    return UserFactory(tenant=tenant_a, email="owner@tenant-a.test")


@pytest.fixture
def user_b(tenant_b):
    return UserFactory(tenant=tenant_b, email="owner@tenant-b.test")


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
