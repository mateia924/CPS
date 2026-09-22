from django.db import migrations

# Kept in sync by hand with apps.access.services.DEFAULT_PERMISSIONS —
# see 0003_seed_permissions.py's note about not importing live app code.
# Sprint 3.5 (3.3 v1.4): the unified Parties screen moved to Settings —
# "الأطراف (عرض شامل)" — gated separately from the ordinary
# parties.view/manage granted broadly to the new per-role screens.
NEW_PERMISSIONS = [
    ("parties.view_all", "View the unified parties screen (all roles at once)"),
]


def seed_new_permissions(apps, schema_editor):
    Permission = apps.get_model("access", "Permission")
    for code, description in NEW_PERMISSIONS:
        Permission.objects.update_or_create(code=code, defaults={"description": description})


def backfill_existing_roles(apps, schema_editor):
    """Additive-only: grant parties.view_all to every existing tenant's
    Owner and Accountant system roles — "مدير الحسابات" in spec terms —
    same system-role-name-based backfill pattern as
    0005_seed_sprint3_permissions.py."""
    Role = apps.get_model("access", "Role")
    Permission = apps.get_model("access", "Permission")

    view_all = Permission.objects.get(code="parties.view_all")
    roles = Role.objects.filter(name__in=["Owner", "Accountant"], is_system=True)
    for role in roles:
        role.permissions.add(view_all)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("access", "0005_seed_sprint3_permissions"),
    ]

    operations = [
        migrations.RunPython(seed_new_permissions, noop),
        migrations.RunPython(backfill_existing_roles, noop),
    ]
