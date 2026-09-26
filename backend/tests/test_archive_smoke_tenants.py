"""§11 standing rule (added alongside this command): every session that
creates a temporary smoke-* tenant ends with `manage.py
archive_smoke_tenants`. One test: it archives a smoke-* tenant and
never touches any other.
"""

import pytest
from django.core.management import call_command

from apps.tenants.models import Tenant

from .factories import TenantFactory


@pytest.mark.django_db
def test_archives_only_smoke_prefixed_tenants():
    smoke_tenant = TenantFactory(subdomain="smoke-1790421727")
    other_tenant = TenantFactory(subdomain="regular-co")

    call_command("archive_smoke_tenants")

    smoke_tenant.refresh_from_db()
    other_tenant.refresh_from_db()
    assert smoke_tenant.status == Tenant.Status.ARCHIVED
    assert other_tenant.status == Tenant.Status.ACTIVE
