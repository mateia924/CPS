"""Sprint 6.6.3 (item 4): "اختبار أن RLS مفعّل على كل جدول مستأجر
(يفحص pg_class.relrowsecurity)" — the structural half of tests/
test_rls.py's own functional proof. Uses the exact same discovery
function the setup migration/command itself uses
(apps.common.rls.tenant_scoped_tables), so a brand-new tenant-scoped
model is automatically covered and this can never silently drift from
what apps.tenants.services.configure_database_roles_and_rls actually
installs.
"""

import pytest
from django.db import connection

from apps.common.rls import tenant_scoped_tables


@pytest.mark.django_db
def test_every_tenant_scoped_table_has_row_level_security_enabled():
    tables = [name for name, _model in tenant_scoped_tables()]
    assert tables, "tenant_scoped_tables() found nothing — the discovery itself is broken"

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relname FROM pg_class WHERE relname = ANY(%s) AND relrowsecurity = true",
            [tables],
        )
        enabled = {row[0] for row in cursor.fetchall()}

    missing = sorted(set(tables) - enabled)
    assert not missing, (
        "Table(s) carry a tenant_id column but RLS is not enabled on them — "
        f"apps.tenants.services.configure_database_roles_and_rls needs a rerun "
        f"(manage.py setup_rls) or these are newly added since it last ran: {missing}"
    )


@pytest.mark.django_db
def test_every_tenant_scoped_table_has_the_tenant_isolation_policy():
    tables = [name for name, _model in tenant_scoped_tables()]

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tablename FROM pg_policies "
            "WHERE schemaname = 'public' AND policyname = 'tenant_isolation' AND tablename = ANY(%s)",
            [tables],
        )
        covered = {row[0] for row in cursor.fetchall()}

    missing = sorted(set(tables) - covered)
    assert not missing, f"Table(s) enabled RLS but have no tenant_isolation policy: {missing}"
