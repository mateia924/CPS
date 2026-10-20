import os

from django.core.management.base import BaseCommand, CommandError

from apps.access.models import Role
from apps.access.services import seed_default_roles
from apps.tenants.models import Tenant

from ...models import User


class Command(BaseCommand):
    """Sprint 6.5.8 (E2E test support): adds a second RBAC-role-holding
    user to an existing tenant. There is no product UI for this yet —
    RolesPage only edits an already-existing TenantUser's roles/entities
    (`POST /users/{id}/assign/`), and RegisterView only ever creates a
    tenant's first user — so this exists purely to let the Playwright
    E2E suite (frontend/e2e/) reach a genuinely multi-user tenant state
    (needed for the emergency-approval scenario) without a browser flow
    that doesn't exist to click through. Restricted to smoke-* tenants
    only, same convention as archive_smoke_tenants — never a real one.

    Rule 50 (2026-10-20, same as anonymize_staging_users): the password is
    read from E2E_TEST_USER_PASSWORD in the environment, never from an
    option — `--password <value>` put it in `ps` for every user on the
    host. `docker exec -e E2E_TEST_USER_PASSWORD …` names the variable,
    not its value. An empty value stops the command before it writes."""

    help = "Create a second login user with one RBAC role on a smoke-* tenant, for E2E test setup only."

    def add_arguments(self, parser):
        parser.add_argument("--subdomain", required=True)
        parser.add_argument("--email", required=True)
        parser.add_argument("--role", required=True, help='RBAC role name, e.g. "Accountant" or "Owner".')

    def handle(self, *args, **options):
        subdomain = options["subdomain"]
        password = os.environ.get("E2E_TEST_USER_PASSWORD", "")
        if not password:
            raise CommandError(
                "E2E_TEST_USER_PASSWORD is empty — it is read from the environment "
                "(docker exec -e E2E_TEST_USER_PASSWORD …), never from the command line."
            )
        if not subdomain.startswith("smoke-"):
            raise CommandError('Refusing to run against a non-"smoke-*" subdomain.')
        try:
            tenant = Tenant.objects.get(subdomain=subdomain)
        except Tenant.DoesNotExist as exc:
            raise CommandError(f"No tenant with subdomain {subdomain!r}.") from exc

        roles = {r.name: r for r in Role.objects.filter(tenant=tenant, is_system=True)}
        if not roles:
            roles = seed_default_roles(tenant)
        role_name = options["role"]
        if role_name not in roles:
            raise CommandError(f"Unknown role {role_name!r}. Available: {sorted(roles)}")

        user = User.objects.create_user(
            tenant=tenant, email=options["email"], password=password, role=User.Role.STAFF,
        )
        user.roles.add(roles[role_name])
        self.stdout.write(self.style.SUCCESS(f"Created {user.email} ({role_name}) on {subdomain}"))
