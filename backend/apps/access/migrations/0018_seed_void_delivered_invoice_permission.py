from django.db import migrations

# Kept in sync by hand with apps.access.services.DEFAULT_PERMISSIONS —
# see 0003_seed_permissions.py's note about not importing live app code.
# Sprint 6.7 (decision 14).
NEW_PERMISSIONS = [
    ("sales.void_delivered_invoice", "Void an invoice that has already been delivered to the customer"),
]

# Owner only — a documented temporary override (C7), never Accountant.
ROLE_GRANTS = {
    "sales.void_delivered_invoice": ["Owner"],
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
        ("access", "0017_seed_accounting_post_permission"),
    ]

    operations = [
        migrations.RunPython(seed_new_permissions, noop),
        migrations.RunPython(backfill_existing_roles, noop),
    ]
