from django.db import migrations

# Kept in sync by hand with apps.access.services.DEFAULT_PERMISSIONS —
# see 0003_seed_permissions.py's note about not importing live app code.
# Sprint 6.5 (decision 15).
NEW_PERMISSIONS = [
    ("assets.depreciate", "Start, add to, or dispose of an asset's depreciation schedule"),
    ("assets.transfer", "Transfer an asset between branches or cost centers"),
]

ROLE_GRANTS = {
    "assets.depreciate": ["Owner", "Accountant"],
    "assets.transfer": ["Owner", "Accountant"],
}


def seed_new_permissions(apps, schema_editor):
    Permission = apps.get_model("access", "Permission")
    for code, description in NEW_PERMISSIONS:
        Permission.objects.update_or_create(code=code, defaults={"description": description})


def backfill_existing_roles(apps, schema_editor):
    Role = apps.get_model("access", "Role")
    Permission = apps.get_model("access", "Permission")

    for code, role_names in ROLE_GRANTS.items():
        permission = Permission.objects.get(code=code)
        for role in Role.objects.filter(name__in=role_names, is_system=True):
            role.permissions.add(permission)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("access", "0018_seed_void_delivered_invoice_permission"),
    ]

    operations = [
        migrations.RunPython(seed_new_permissions, noop),
        migrations.RunPython(backfill_existing_roles, noop),
    ]
