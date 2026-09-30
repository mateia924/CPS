"""Sprint 6.6.0: apps.accounts.management.commands.reset_passwords_for_staging
— scripts/staging_refresh.sh's own last step. This is a destructive,
tenant-wide password overwrite by design, so the one thing worth a real
test is that it hard-refuses everywhere except CPS_ENVIRONMENT=staging,
and that it actually rewrites every user's password (not just some)
when it does run. Real Postgres throughout (§11)."""

import pytest
from django.core.management import CommandError, call_command

from .factories import TenantFactory, UserFactory


@pytest.mark.django_db
def test_refuses_outside_staging(monkeypatch):
    monkeypatch.delenv("CPS_ENVIRONMENT", raising=False)
    tenant = TenantFactory()
    user = UserFactory(tenant=tenant)
    old_password_hash = user.password

    with pytest.raises(CommandError, match="staging"):
        call_command("reset_passwords_for_staging", "--password", "Whatever123!")

    user.refresh_from_db()
    assert user.password == old_password_hash


@pytest.mark.django_db
def test_refuses_when_environment_is_production(monkeypatch):
    monkeypatch.setenv("CPS_ENVIRONMENT", "production")
    TenantFactory()
    with pytest.raises(CommandError, match="staging"):
        call_command("reset_passwords_for_staging", "--password", "Whatever123!")


@pytest.mark.django_db
def test_rewrites_every_users_password_when_staging(monkeypatch):
    monkeypatch.setenv("CPS_ENVIRONMENT", "staging")
    tenant_a = TenantFactory()
    tenant_b = TenantFactory()
    user_a = UserFactory(tenant=tenant_a, email="owner@a.test")
    user_b = UserFactory(tenant=tenant_b, email="owner@b.test")

    call_command("reset_passwords_for_staging", "--password", "Staging@2026!")

    user_a.refresh_from_db()
    user_b.refresh_from_db()
    # Real emails are never touched — only the password.
    assert user_a.email == "owner@a.test"
    assert user_b.email == "owner@b.test"
    assert user_a.check_password("Staging@2026!")
    assert user_b.check_password("Staging@2026!")


@pytest.mark.django_db
def test_skip_guard_env_var_does_not_bypass_this_command(monkeypatch):
    """CPS_SKIP_BACKUP_GUARD is apps.tenants's own migrate-guard escape
    hatch — unrelated to this command, which must never honor it (a
    password-reset override warrants its own explicit gate, not
    borrowing someone else's emergency bypass by accident)."""
    monkeypatch.setenv("CPS_SKIP_BACKUP_GUARD", "1")
    monkeypatch.delenv("CPS_ENVIRONMENT", raising=False)
    TenantFactory()
    with pytest.raises(CommandError, match="staging"):
        call_command("reset_passwords_for_staging", "--password", "Whatever123!")
