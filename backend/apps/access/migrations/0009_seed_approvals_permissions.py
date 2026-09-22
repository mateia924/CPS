from django.db import migrations

# Kept in sync by hand with apps.access.services.DEFAULT_PERMISSIONS — see
# 0003_seed_permissions.py's note about not importing live app code.
# Sprint 4.5 (3.15.1): approval rules + inbox.
NEW_PERMISSIONS = [
    ("approvals.view", "View approval rules and the approval inbox"),
    ("approvals.manage", "Create, edit and deactivate approval rules"),
]


def seed_new_permissions(apps, schema_editor):
    Permission = apps.get_model("access", "Permission")
    for code, description in NEW_PERMISSIONS:
        Permission.objects.update_or_create(code=code, defaults={"description": description})


def backfill_existing_roles(apps, schema_editor):
    """Owner gets both (SYSTEM_ROLES: None = every permission);
    Accountant gets approvals.view only — approvals.manage (editing the
    rules that gate approval itself) stays Owner-only, same reasoning
    as 3.15.9's control matrix keeping chart-of-accounts edits and
    approval authority separate from day-to-day bookkeeping."""
    Role = apps.get_model("access", "Role")
    Permission = apps.get_model("access", "Permission")

    view = Permission.objects.get(code="approvals.view")
    manage = Permission.objects.get(code="approvals.manage")

    for role in Role.objects.filter(name="Owner", is_system=True):
        role.permissions.add(view, manage)
    for role in Role.objects.filter(name="Accountant", is_system=True):
        role.permissions.add(view)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("access", "0008_seed_accounting_manage_permission"),
    ]

    operations = [
        migrations.RunPython(seed_new_permissions, noop),
        migrations.RunPython(backfill_existing_roles, noop),
    ]
