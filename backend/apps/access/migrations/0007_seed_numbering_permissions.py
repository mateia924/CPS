from django.db import migrations

# Kept in sync by hand with apps.access.services.DEFAULT_PERMISSIONS — see
# 0003_seed_permissions.py's note about not importing live app code.
# Sprint 4.1 (3.4/3.18): Settings ← "ترقيم المستندات".
NEW_PERMISSIONS = [
    ("numbering.view", "View document numbering settings"),
    ("numbering.manage", "Edit document numbering prefixes and yearly reset"),
]


def seed_new_permissions(apps, schema_editor):
    Permission = apps.get_model("access", "Permission")
    for code, description in NEW_PERMISSIONS:
        Permission.objects.update_or_create(code=code, defaults={"description": description})


def backfill_existing_roles(apps, schema_editor):
    """Owner's SYSTEM_ROLES entry is `None` (= "every permission"), but
    that's only applied live at seed_default_roles() time (tenant
    registration) — an existing tenant's Owner role needs both new
    codes granted explicitly here, same as every prior sprint's
    permission-seeding migration. Accountant only gets numbering.view
    per SYSTEM_ROLES (numbering.manage is Owner-only)."""
    Role = apps.get_model("access", "Role")
    Permission = apps.get_model("access", "Permission")

    view = Permission.objects.get(code="numbering.view")
    manage = Permission.objects.get(code="numbering.manage")

    for role in Role.objects.filter(name="Owner", is_system=True):
        role.permissions.add(view, manage)
    for role in Role.objects.filter(name="Accountant", is_system=True):
        role.permissions.add(view)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("access", "0006_seed_sprint35_permissions"),
    ]

    operations = [
        migrations.RunPython(seed_new_permissions, noop),
        migrations.RunPython(backfill_existing_roles, noop),
    ]
