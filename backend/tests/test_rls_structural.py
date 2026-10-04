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


@pytest.mark.django_db
def test_configure_database_roles_and_rls_skips_a_table_that_does_not_exist_yet(monkeypatch):
    """Sprint 7.0 (CI #67 follow-up): the exact crash found while adding
    apps.inventory — tenant_scoped_tables() reads the LIVE model
    registry, so on a cold `--create-db` replay, migration 0016's own
    RunPython could hit a table a LATER migration (in another app)
    hasn't created yet, and die with "relation ... does not exist"
    before ever reaching the real tables after it in the list. This is
    the negative test: a bogus, genuinely nonexistent table injected
    FIRST in tenant_scoped_tables()' own return value must not abort
    the whole function — and a real table appearing AFTER it in the
    list must still get its policy, proving the skip doesn't just
    swallow everything that follows."""
    from apps.common import rls
    from apps.tenants.services import configure_database_roles_and_rls

    real_tables = tenant_scoped_tables()
    assert real_tables, "tenant_scoped_tables() found nothing to test against"
    real_table_name, real_model = real_tables[0]

    def _fake_tenant_scoped_tables():
        return [("sprint7_table_does_not_exist", None), (real_table_name, real_model)]

    monkeypatch.setattr(rls, "tenant_scoped_tables", _fake_tenant_scoped_tables)

    configure_database_roles_and_rls(connection)  # must not raise

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM pg_policies WHERE schemaname = 'public' "
            "AND policyname = 'tenant_isolation' AND tablename = %s",
            [real_table_name],
        )
        assert cursor.fetchone() is not None, (
            f"{real_table_name} (listed AFTER the nonexistent table) never got its policy — "
            "the skip is swallowing real tables too, not just the missing one."
        )
