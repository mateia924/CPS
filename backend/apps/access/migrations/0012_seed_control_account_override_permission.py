from django.db import migrations

# Kept in sync by hand with apps.access.services.DEFAULT_PERMISSIONS —
# see 0003_seed_permissions.py's note about not importing live app code.
# Sprint 5.7 (CFO_REVIEW_1 C2).
NEW_PERMISSIONS = [
    ("accounting.post_control_accounts", "Override the manual-posting block on a control account"),
]


def seed_new_permissions(apps, schema_editor):
    Permission = apps.get_model("access", "Permission")
    for code, description in NEW_PERMISSIONS:
        Permission.objects.update_or_create(code=code, defaults={"description": description})


def backfill_existing_roles(apps, schema_editor):
    """Owner only — this project has no separate "مدير حسابات" role,
    and the control matrix means this stays an elevated, deliberately
    rare grant rather than ordinary day-to-day Accountant work. A new
    tenant's Owner role gets it automatically (SYSTEM_ROLES: None means
    every permission); existing Owner roles need it granted explicitly
    here, same as every prior seed-permission migration in this app."""
    Role = apps.get_model("access", "Role")
    Permission = apps.get_model("access", "Permission")

    permission = Permission.objects.get(code="accounting.post_control_accounts")
    for role in Role.objects.filter(name="Owner", is_system=True):
        role.permissions.add(permission)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("access", "0011_seed_voucher_permissions"),
    ]

    operations = [
        migrations.RunPython(seed_new_permissions, noop),
        migrations.RunPython(backfill_existing_roles, noop),
    ]
