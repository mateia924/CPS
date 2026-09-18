from django.db import migrations

# docs/SYSTEM_ANALYSIS.md 3.14 sprint 2 spec: "صلاحيات قاعدة البيانات:
# INSERT و SELECT فقط للدور الذي يستخدمه التطبيق (يجب توثيق الطريقة)".
#
# A plain `REVOKE UPDATE, DELETE ... FROM <role>` was the first thing
# tried here, but it does NOT work in this deployment: this project's
# single Postgres role (read via `SELECT current_user` below — it's
# whatever POSTGRES_USER is in .env, "cps" on this dev host) both runs
# migrations AND is what the Django app connects as, which makes it the
# OWNER of platform_auditlog. Table owners retain full privileges on
# their own tables regardless of any REVOKE — PostgreSQL does not let an
# owner revoke its own implicit owner privileges via GRANT/REVOKE. A
# genuinely separate, lower-privileged runtime role would need its own
# deployment-config change (a second DATABASE_URL) that's out of scope
# for this sprint.
#
# So immutability is enforced instead with a BEFORE UPDATE OR DELETE
# trigger that unconditionally raises an exception — this holds
# regardless of which role/ownership issues the UPDATE/DELETE,
# including the table owner and even a superuser, and needs no separate
# DB role to be effective. This is the "documented method" the spec
# asks for.


CREATE_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION platform_auditlog_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'platform_auditlog is append-only: % is not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER platform_auditlog_no_update_delete
    BEFORE UPDATE OR DELETE ON platform_auditlog
    FOR EACH ROW EXECUTE FUNCTION platform_auditlog_immutable();
"""

DROP_TRIGGER_SQL = """
DROP TRIGGER IF EXISTS platform_auditlog_no_update_delete ON platform_auditlog;
DROP FUNCTION IF EXISTS platform_auditlog_immutable();
"""


def install_trigger(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(CREATE_TRIGGER_SQL)


def remove_trigger(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(DROP_TRIGGER_SQL)


class Migration(migrations.Migration):

    dependencies = [
        ("platform", "0002_seed_plans"),
    ]

    operations = [
        migrations.RunPython(install_trigger, remove_trigger),
    ]
