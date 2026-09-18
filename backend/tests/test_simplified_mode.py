"""docs/SYSTEM_ANALYSIS.md 3.13: a tenant with exactly one company and
one branch (and no holding) is in simplified mode — the org structure
is meant to stay invisible to that customer. Adding a second branch
takes them out of it.
"""

import pytest
from rest_framework.test import APIClient

from apps.organization.models import LegalEntity


@pytest.mark.django_db
def test_new_tenant_is_simplified_by_default():
    client = APIClient()
    register = client.post(
        "/api/auth/register/",
        {
            "company_name": "Simple Co",
            "subdomain": "simple-co",
            "email": "owner@simple-co.test",
            "password": "SimplePass!2026",
        },
        format="json",
    )
    assert register.status_code == 201

    client.credentials(HTTP_AUTHORIZATION=f"Bearer {register.data['access']}")
    me = client.get("/api/auth/me/")
    assert me.status_code == 200
    assert me.data["simplified_mode"] is True
    # Sprint 2 (3.14): a new self-registered tenant now starts on the
    # Free plan ("invoicing only"), which does not include organization
    # structure or cost centers — a deliberate change from sprint 1,
    # where every tenant got both by default with no plan concept yet.
    assert me.data["features"]["organization"] is False
    assert me.data["features"]["cost_centers"] is False
    assert me.data["features"]["inventory"] is False


@pytest.mark.django_db
def test_adding_second_branch_turns_off_simplified_mode():
    client = APIClient()
    register = client.post(
        "/api/auth/register/",
        {
            "company_name": "Growing Co",
            "subdomain": "growing-co",
            "email": "owner@growing-co.test",
            "password": "GrowingPass!2026",
        },
        format="json",
    )
    tenant_id = register.data["tenant"]["id"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {register.data['access']}")

    company = LegalEntity.objects.get(tenant_id=tenant_id, entity_type=LegalEntity.Type.COMPANY)
    created = client.post(
        "/api/legal-entities/",
        {"code": "BR-02", "name": "Second Branch", "entity_type": "branch", "parent": str(company.id)},
        format="json",
    )
    assert created.status_code == 201

    me = client.get("/api/auth/me/")
    assert me.data["simplified_mode"] is False
