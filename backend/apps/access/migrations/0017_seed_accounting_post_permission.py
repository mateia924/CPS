from django.db import migrations

# Kept in sync by hand with apps.access.services.DEFAULT_PERMISSIONS —
# see 0003_seed_permissions.py's note about not importing live app code.
# Sprint 6.4 (decision 10).
NEW_PERMISSIONS = [
    ("accounting.post", "Generate due recurring-entry installments on demand"),
]

# Which existing system roles get which new permission — matches
# apps.access.services.SYSTEM_ROLES (Owner is seeded with every
# permission that exists *at registration time*, not dynamically, so
# existing Owner roles need this backfill just like Accountant does).
ROLE_GRANTS = {
    "accounting.post": ["Owner", "Accountant"],
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
        ("access", "0016_seed_fiscal_period_permissions"),
    ]

    operations = [
        migrations.RunPython(seed_new_permissions, noop),
        migrations.RunPython(backfill_existing_roles, noop),
    ]
