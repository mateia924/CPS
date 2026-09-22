from django.db import migrations

# Kept in sync by hand with apps.access.services.DEFAULT_PERMISSIONS — see
# 0003_seed_permissions.py's note about not importing live app code.
# Sprint 4.3 (3.15.9): chart-of-accounts write actions — Settings/
# المحاسبة ← دليل الحسابات.
NEW_PERMISSIONS = [
    ("accounting.manage", "Create, edit and deactivate accounts in the chart of accounts"),
]


def seed_new_permissions(apps, schema_editor):
    Permission = apps.get_model("access", "Permission")
    for code, description in NEW_PERMISSIONS:
        Permission.objects.update_or_create(code=code, defaults={"description": description})


def backfill_existing_roles(apps, schema_editor):
    """3.15.9: "تعديل دليل الحسابات: مدير حسابات" — Owner (implicitly
    "every permission" via SYSTEM_ROLES) and Accountant (the closest
    match to "مدير حسابات" in this project's role system)."""
    Role = apps.get_model("access", "Role")
    Permission = apps.get_model("access", "Permission")

    manage = Permission.objects.get(code="accounting.manage")
    for role in Role.objects.filter(name__in=["Owner", "Accountant"], is_system=True):
        role.permissions.add(manage)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("access", "0007_seed_numbering_permissions"),
    ]

    operations = [
        migrations.RunPython(seed_new_permissions, noop),
        migrations.RunPython(backfill_existing_roles, noop),
    ]
