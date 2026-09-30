from django.core.management.base import BaseCommand
from django.db import connection

from apps.tenants.services import configure_database_roles_and_rls


class Command(BaseCommand):
    """Sprint 6.6.3 (item 1): idempotent — re-applies the `cps_app`
    role's grants and every tenant_isolation policy. The migration
    (apps.tenants.migrations.0016_row_level_security) already runs
    this once; this command exists so scripts/staging_refresh.sh can
    re-run the SAME logic after every restore, since `pg_dump
    --no-privileges` (backup.sh) strips every GRANT from the dump and
    `manage.py migrate` never replays an already-applied migration
    against a restored database."""

    help = "Re-apply the cps_app role's grants and RLS policies (idempotent)."

    def handle(self, *args, **options):
        configure_database_roles_and_rls(connection)
        self.stdout.write(self.style.SUCCESS("RLS roles/grants/policies configured."))
