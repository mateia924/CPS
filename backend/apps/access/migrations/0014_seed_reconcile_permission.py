from django.db import migrations

# Kept in sync by hand with apps.access.services.DEFAULT_PERMISSIONS —
# see 0003_seed_permissions.py's note about not importing live app code.
# Sprint 5.5 (block 5.5.1).
NEW_PERMISSIONS = [
    ("treasury.reconcile", "Import bank statements and match statement lines"),
]


def seed_new_permissions(apps, schema_editor):
    Permission = apps.get_model("access", "Permission")
    for code, description in NEW_PERMISSIONS:
        Permission.objects.update_or_create(code=code, defaults={"description": description})


def backfill_existing_roles(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    Permission = apps.get_model("access", "Permission")

    permission = Permission.objects.get(code="treasury.reconcile")
    for role in Role.objects.filter(name__in=["Owner", "Accountant"], is_system=True):
        role.permissions.add(permission)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("access", "0013_seed_iban_change_permission"),
    ]

    operations = [
        migrations.RunPython(seed_new_permissions, noop),
        migrations.RunPython(backfill_existing_roles, noop),
    ]
