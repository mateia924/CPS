"""Sprint 4.8 (rule 12/"GET بلا آثار جانبية"): GET /api/auth/me/ must
be a pure read — it must never create rows as a side effect of being
called, and it must return a full permissions/features list even for a
tenant with none of sprint 4's per-tenant records (tax periods, tax
codes, chart of accounts, approval rules) — whether that's a brand-new
tenant that happens to have none of those, or a tenant that predates
sprint 4 entirely and was never backfilled with them.
"""

import pytest
from rest_framework.test import APIClient

from apps.access.services import seed_default_roles
from apps.accounting.models import TaxCode, TaxPeriod
from apps.organization.services import create_default_legal_entities
from apps.tenants.models import TenantFeatures

from .factories import TenantFactory, UserFactory


def _bare_tenant_with_owner(subdomain):
    """A tenant with only what every tenant has always had since
    sprint 1 (legal entities + system roles) — deliberately skips
    everything sprint 4 added per-tenant (seed_chart_of_accounts,
    seed_tax_codes_for_country, generate_tax_periods_for_year,
    the default ApprovalRule, and any TenantFeatures row), to stand in
    for a tenant registered before sprint 4 existed and never
    retroactively backfilled with per-tenant data (only the global
    permission catalog / Owner role grants are backfilled by migration
    — see apps/access/migrations/000{7,8,9}_seed_*_permissions.py).
    """
    tenant = TenantFactory(subdomain=subdomain)
    create_default_legal_entities(tenant, tenant.name)
    user = UserFactory(tenant=tenant, email=f"owner@{subdomain}.test")
    roles = seed_default_roles(tenant)
    user.roles.add(roles["Owner"])
    return tenant, user


@pytest.mark.django_db
def test_me_for_tenant_with_no_tax_periods_returns_full_list():
    tenant, user = _bare_tenant_with_owner("me-no-tax-periods")
    assert not TaxPeriod.objects.filter(tenant=tenant).exists()
    assert not TaxCode.objects.filter(tenant=tenant).exists()

    client = APIClient()
    client.force_authenticate(user=user)
    response = client.get("/api/auth/me/")

    assert response.status_code == 200
    assert "accounting.view" in response.data["permissions"]
    assert "approvals.view" in response.data["permissions"]
    assert set(response.data["features"]) == {
        "organization", "cost_centers", "inventory", "purchasing", "hr", "treasury", "assets",
    }
    # The GET itself must not have generated anything.
    assert not TaxPeriod.objects.filter(tenant=tenant).exists()


@pytest.mark.django_db
def test_me_for_pre_sprint4_tenant_returns_full_list_without_writing():
    """A tenant with no TenantFeatures row at all (the pre-sprint-2
    state, before that model existed) must not crash, must not have a
    row created for it by the GET, and must still return a complete
    response — MeView.features falls back to an unsaved in-memory
    TenantFeatures instance instead of `.create()`-ing one.
    """
    tenant, user = _bare_tenant_with_owner("me-pre-sprint4")
    assert not TenantFeatures.objects.filter(tenant=tenant).exists()

    client = APIClient()
    client.force_authenticate(user=user)
    response = client.get("/api/auth/me/")

    assert response.status_code == 200
    assert response.data["roles"] == ["Owner"]
    assert "numbering.view" in response.data["permissions"]
    assert response.data["features"]["treasury"] is False

    # A GET must never write — the row still must not exist afterward.
    assert not TenantFeatures.objects.filter(tenant=tenant).exists()

    # Calling it again (e.g. a second page load) must behave identically.
    response2 = client.get("/api/auth/me/")
    assert response2.status_code == 200
    assert not TenantFeatures.objects.filter(tenant=tenant).exists()
