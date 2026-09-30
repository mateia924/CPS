"""Sprint 6.6.0: apps.accounts.management.commands.anonymize_staging_users
— scripts/staging_refresh.sh's own last step. Destructive by design
(every user's email AND password get rewritten), so the real things
worth testing: it hard-refuses everywhere except CPS_ENVIRONMENT=staging,
it rewrites every user (not just some), the email pattern is exactly
"<local part>@<tenant subdomain>.staging.test", and a same-tenant
local-part collision after rewriting gets disambiguated instead of
crashing. Real Postgres throughout (§11)."""

import pytest
from django.core.management import CommandError, call_command

from .factories import TenantFactory, UserFactory


@pytest.mark.django_db
def test_refuses_outside_staging(monkeypatch):
    monkeypatch.delenv("CPS_ENVIRONMENT", raising=False)
    tenant = TenantFactory()
    user = UserFactory(tenant=tenant, email="owner@example.test")
    old_password_hash = user.password

    with pytest.raises(CommandError, match="staging"):
        call_command("anonymize_staging_users", "--password", "Whatever123!")

    user.refresh_from_db()
    assert user.password == old_password_hash
    assert user.email == "owner@example.test"


@pytest.mark.django_db
def test_refuses_when_environment_is_production(monkeypatch):
    monkeypatch.setenv("CPS_ENVIRONMENT", "production")
    TenantFactory()
    with pytest.raises(CommandError, match="staging"):
        call_command("anonymize_staging_users", "--password", "Whatever123!")


@pytest.mark.django_db
def test_rewrites_email_domain_and_password_when_staging(monkeypatch):
    monkeypatch.setenv("CPS_ENVIRONMENT", "staging")
    tenant_a = TenantFactory(subdomain="fatma")
    tenant_b = TenantFactory(subdomain="acme")
    # A real-looking address (Fatma's own Owner login is a real Gmail
    # address, not a synthetic .test one) — this is exactly the case
    # the whole feature exists for.
    user_a = UserFactory(tenant=tenant_a, email="fatmaelzhraaabukhdra@gmail.com")
    user_b = UserFactory(tenant=tenant_b, email="owner@acme.test")

    call_command("anonymize_staging_users", "--password", "Staging@2026!")

    user_a.refresh_from_db()
    user_b.refresh_from_db()
    # Local part kept, domain replaced with "<subdomain>.staging.test".
    assert user_a.email == "fatmaelzhraaabukhdra@fatma.staging.test"
    assert user_b.email == "owner@acme.staging.test"
    assert user_a.check_password("Staging@2026!")
    assert user_b.check_password("Staging@2026!")


@pytest.mark.django_db
def test_local_part_collision_within_a_tenant_gets_disambiguated(monkeypatch):
    monkeypatch.setenv("CPS_ENVIRONMENT", "staging")
    tenant = TenantFactory(subdomain="fatma")
    user_a = UserFactory(tenant=tenant, email="owner@gmail.com")
    user_b = UserFactory(tenant=tenant, email="owner@yahoo.com")

    call_command("anonymize_staging_users", "--password", "Staging@2026!")

    user_a.refresh_from_db()
    user_b.refresh_from_db()
    emails = {user_a.email, user_b.email}
    assert emails == {"owner@fatma.staging.test", "owner-2@fatma.staging.test"}


@pytest.mark.django_db
def test_skip_guard_env_var_does_not_bypass_this_command(monkeypatch):
    """CPS_SKIP_BACKUP_GUARD is apps.tenants's own migrate-guard escape
    hatch — unrelated to this command, which must never honor it (an
    anonymization override warrants its own explicit gate, not
    borrowing someone else's emergency bypass by accident)."""
    monkeypatch.setenv("CPS_SKIP_BACKUP_GUARD", "1")
    monkeypatch.delenv("CPS_ENVIRONMENT", raising=False)
    TenantFactory()
    with pytest.raises(CommandError, match="staging"):
        call_command("anonymize_staging_users", "--password", "Whatever123!")
