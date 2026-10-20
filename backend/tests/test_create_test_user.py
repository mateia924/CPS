"""Rule 50 (2026-10-20): create_test_user (e2e setup only) takes the new
user's password from E2E_TEST_USER_PASSWORD in the environment, never from
an option — the same fix anonymize_staging_users got on 2026-10-18.
`--password <value>` put the secret in `ps` for every user on the host."""

import pytest
from django.core.management import CommandError, call_command

from apps.accounts.models import User

from .factories import TenantFactory


@pytest.mark.django_db
def test_create_test_user_takes_the_password_from_the_environment_never_from_the_command_line(monkeypatch):
    TenantFactory(subdomain="smoke-ctu")
    with pytest.raises(CommandError, match="unrecognized arguments: --password"):
        call_command(
            "create_test_user", "--subdomain", "smoke-ctu", "--email", "a@smoke-ctu.test",
            "--password", "on-the-command-line", "--role", "Accountant",
        )

    monkeypatch.delenv("E2E_TEST_USER_PASSWORD", raising=False)
    with pytest.raises(CommandError, match="E2E_TEST_USER_PASSWORD is empty"):
        call_command("create_test_user", "--subdomain", "smoke-ctu", "--email", "a@smoke-ctu.test", "--role", "Accountant")
    assert not User.objects.filter(email="a@smoke-ctu.test").exists()

    secret = "-".join(["Ctu", "Env", "2026!x"])
    monkeypatch.setenv("E2E_TEST_USER_PASSWORD", secret)
    call_command("create_test_user", "--subdomain", "smoke-ctu", "--email", "a@smoke-ctu.test", "--role", "Accountant")
    user = User.objects.get(email="a@smoke-ctu.test")
    assert user.check_password(secret)
    assert list(user.roles.values_list("name", flat=True)) == ["Accountant"]
