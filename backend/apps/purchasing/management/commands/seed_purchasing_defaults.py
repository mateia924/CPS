from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from apps.common.rls import set_local_tenant_id
from apps.purchasing.services import seed_purchasing_defaults
from apps.tenants.models import Tenant


class _DryRun(Exception):
    pass


class Command(BaseCommand):
    """Sprint 8.0, made ADDITIVE ONLY by the owner's decision of 2026-10-20:
    on tenants that predate purchasing it creates what is missing — the
    purchasing system accounts, the withholding codes (examples), the
    purchasing.* permission rows, the Purchasing role (view/manage, no
    users) and the five purchasing approval rules (min_amount=0 -> Owner) —
    and modifies NO existing role or row. Nobody's access changes; the
    owner grants purchasing on the roles screen when she wants it.

    The approval rules are why it exists at all: a document type with no
    ApprovalRule is approved automatically (the 7.4 incident).

    The target is always explicit — --tenant (repeatable) or
    --all-tenants; no argument refuses. Archived tenants are never
    processed. --dry-run prints exactly what a real run would add, inside
    a transaction that is rolled back. Idempotent: a second run adds
    nothing. Reads the same definitions registration does
    (apps.purchasing.services.seed_purchasing_defaults)."""

    help = "Create purchasing's accounts, withholding codes, permissions, Purchasing role and approval rules where missing; modifies no existing role (idempotent)."

    def add_arguments(self, parser):
        target = parser.add_mutually_exclusive_group()
        target.add_argument("--tenant", action="append", default=[], help="A tenant's subdomain; repeat for several.")
        target.add_argument("--all-tenants", action="store_true", help="Every non-archived tenant.")
        parser.add_argument("--dry-run", action="store_true", help="Print what would be added; write nothing.")

    def handle(self, *args, **options):
        if not options["tenant"] and not options["all_tenants"]:
            raise CommandError("Name the target: --tenant <subdomain> (repeatable) or --all-tenants.")
        if options["all_tenants"]:
            tenants = list(Tenant.objects.exclude(status=Tenant.Status.ARCHIVED).order_by("subdomain"))
            archived = sorted(Tenant.objects.filter(status=Tenant.Status.ARCHIVED).values_list("subdomain", flat=True))
            if archived:
                self.stdout.write(f"Excluding {len(archived)} archived tenant(s): {', '.join(archived)}")
        else:
            tenants = []
            for subdomain in options["tenant"]:
                tenant = Tenant.objects.filter(subdomain=subdomain).first()
                if tenant is None:
                    raise CommandError(f"No tenant with subdomain {subdomain!r}.")
                if tenant.status == Tenant.Status.ARCHIVED:
                    raise CommandError(f"{subdomain} is archived — refusing.")
                tenants.append(tenant)

        mode = "DRY RUN — nothing written" if options["dry_run"] else "writing"
        self.stdout.write(f"{len(tenants)} tenant(s), {mode}.")
        failures = []
        changed = 0
        for tenant in tenants:
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        set_local_tenant_id(cursor, tenant.id)
                    result = seed_purchasing_defaults(tenant)
                    if options["dry_run"]:
                        raise _DryRun
            except _DryRun:
                pass
            changed += self._report(tenant, result)
            if result["rules_not_active"]:
                failures.append(tenant.subdomain)

        self.stdout.write(f"{changed} tenant(s) {'would change' if options['dry_run'] else 'changed'}.")
        if failures:
            raise CommandError(
                f"Not complete for {failures}: see 'rule not active' above. "
                "Nothing reports success while a purchasing approval rule is absent."
            )

    def _report(self, tenant, result):
        lines = []
        for account in result["accounts_created"]:
            lines.append(f"  account created: {account}")
        for country, count in sorted(result["wht_created"].items()):
            lines.append(f"  withholding codes created: {country} x{count} (examples)")
        if result["permissions_created"]:
            lines.append(f"  permission rows created: {', '.join(result['permissions_created'])}")
        for name in result["roles_created"]:
            lines.append(f"  role created: {name} (no users)")
        if result["rules_created"]:
            lines.append(f"  approval rules created (min=0 -> Owner): {', '.join(result['rules_created'])}")
        for doc_type in result["rules_not_active"]:
            lines.append(f"  RULE NOT ACTIVE: {doc_type} (no Owner role, or an inactive/deleted rule exists)")
        self.stdout.write(f"{tenant.subdomain}: {'no change' if not lines else ''}")
        for line in lines:
            self.stdout.write(line)
        self.stdout.write("  existing roles: unchanged (additive only)")
        changed = any(
            result[key] for key in ("accounts_created", "wht_created", "permissions_created", "roles_created", "rules_created")
        )
        return int(changed)
