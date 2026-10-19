from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from apps.common.rls import set_local_tenant_id
from apps.purchasing.services import (
    WithholdingTableError,
    load_withholding_codes,
    tenant_country_codes,
    withholding_table,
)
from apps.tenants.models import Tenant


class Command(BaseCommand):
    """Sprint 8.0 (D6): load apps/compliance/<country>/withholding.json
    into every tenant whose legal entities sit in that country.

    Idempotent (get_or_create per tenant/country/code): a second run
    creates nothing, and never changes an existing row — an owner's
    approval (is_example=False) or edited rate survives every re-run.
    Every table is checked before the first tenant is touched, so a bad
    entry stops the command with nothing loaded. Archived tenants are
    excluded and named, same as add_missing_system_accounts."""

    help = "Load the per-country withholding tax codes (as examples) into every tenant that lacks them (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", default=None, help="Only this tenant's subdomain, instead of every tenant.")

    def handle(self, *args, **options):
        tenants = Tenant.objects.exclude(status=Tenant.Status.ARCHIVED).order_by("subdomain")
        archived = Tenant.objects.filter(status=Tenant.Status.ARCHIVED)
        if options["tenant"]:
            tenants = tenants.filter(subdomain=options["tenant"])
            archived = archived.filter(subdomain=options["tenant"])
            if not tenants.exists() and not archived.exists():
                raise CommandError(f"No tenant with subdomain {options['tenant']!r}.")
        archived_names = sorted(archived.values_list("subdomain", flat=True))
        if archived_names:
            self.stdout.write(f"Excluding {len(archived_names)} archived tenant(s) (not processed): {', '.join(archived_names)}")

        plan = [(tenant, tenant_country_codes(tenant)) for tenant in tenants]
        try:
            for country in sorted({c for _t, countries in plan for c in countries}):
                withholding_table(country)
        except WithholdingTableError as exc:
            raise CommandError(f"Nothing loaded: {exc}") from None

        created_total = 0
        for tenant, countries in plan:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    set_local_tenant_id(cursor, tenant.id)
                for country in countries:
                    created = load_withholding_codes(tenant, country)
                    created_total += created
                    if created:
                        self.stdout.write(f"{tenant.subdomain}: {created} {country} code(s) created (examples)")
        self.stdout.write(
            self.style.SUCCESS(f"{len(plan)} tenant(s) processed, {created_total} code(s) created.")
        )
