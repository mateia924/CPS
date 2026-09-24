from django.db import migrations

# Kept in sync by hand with apps.access.services.DEFAULT_PERMISSIONS —
# see 0003_seed_permissions.py's note about not importing live app code.
# Sprint 6.1.
NEW_PERMISSIONS = [
    ("accounting.manage_fiscal_periods", "Create and edit fiscal years and periods"),
    ("accounting.close_period", "Close a fiscal period"),
    ("accounting.reopen_period", "Reopen a closed fiscal period"),
    ("accounting.lock_period", "Lock a fiscal period permanently"),
]

# Which existing system roles get which new permission — matches
# apps.access.services.SYSTEM_ROLES (Owner is seeded with every
# permission that exists *at registration time*, not dynamically, so
# existing Owner roles need this backfill just like Accountant does).
ROLE_GRANTS = {
    "accounting.manage_fiscal_periods": ["Owner"],
    "accounting.close_period": ["Owner", "Accountant"],
    "accounting.reopen_period": ["Owner"],
    "accounting.lock_period": ["Owner"],
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
        ("access", "0015_seed_count_cash_permission"),
    ]

    operations = [
        migrations.RunPython(seed_new_permissions, noop),
        migrations.RunPython(backfill_existing_roles, noop),
    ]
