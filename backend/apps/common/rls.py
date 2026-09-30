"""Sprint 6.6.3 (item 1): shared, introspection-based discovery of
"every table that holds a tenant_id column" — used by both the RLS
setup migration/command (apps.tenants.services) and the structural test
that verifies RLS is actually enabled on each one
(tests/test_rls_structural.py), so the two can never silently drift
apart the way a hand-maintained list would."""

import uuid

from django.apps import apps


def set_local_tenant_id(cursor, tenant_id):
    """Sprint 6.6.3 (item 1): `SET LOCAL <custom_guc> = value` does not
    accept a bind parameter for `value` at all — Postgres's own parser
    rejects a prepared-statement placeholder there ("syntax error at or
    near $1"), for every SET/SET LOCAL statement, not a psycopg quirk.
    Safe to inline directly here rather than bind: `uuid.UUID(...)`
    both validates and normalizes `tenant_id` first, and its `str()` is
    always exactly 32 hex digits and 4 dashes — incapable of containing
    a quote or any other SQL metacharacter, so this can never be an
    injection vector regardless of where `tenant_id` originally came
    from."""
    cursor.execute(f"SET LOCAL cps.tenant_id = '{uuid.UUID(str(tenant_id))}'")


def clear_local_tenant_id(cursor):
    cursor.execute("SET LOCAL cps.tenant_id = DEFAULT")


def tenant_scoped_tables():
    """Every concrete model with a column literally named `tenant_id`
    — covers both TenantScopedModel's own `tenant` FK (Django names its
    column `tenant_id` by convention) and a plain UUIDField named
    `tenant_id` with no FK (apps.platform.models.AuditLog). Returns
    (model, db_table) pairs, deduplicated by table."""
    seen = {}
    for model in apps.get_models():
        if model._meta.proxy:
            continue
        for field in model._meta.local_fields:
            if getattr(field, "column", None) == "tenant_id":
                seen[model._meta.db_table] = model
                break
    return sorted(seen.items())
