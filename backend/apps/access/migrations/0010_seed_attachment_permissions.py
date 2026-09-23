from django.db import migrations

# Kept in sync by hand with apps.access.services.DEFAULT_PERMISSIONS — see
# 0003_seed_permissions.py's note about not importing live app code.
# Sprint 5.1 (3.17): every AttachmentPanel.
NEW_PERMISSIONS = [
    ("attachments.view", "View attachments"),
    ("attachments.manage", "Upload and void attachments"),
]


def seed_new_permissions(apps, schema_editor):
    Permission = apps.get_model("access", "Permission")
    for code, description in NEW_PERMISSIONS:
        Permission.objects.update_or_create(code=code, defaults={"description": description})


def backfill_existing_roles(apps, schema_editor):
    """Owner gets both (SYSTEM_ROLES: None = every permission);
    Accountant/Sales get both (day-to-day uploaders); Viewer gets view
    only — same split as apps.access.services.SYSTEM_ROLES."""
    Role = apps.get_model("access", "Role")
    Permission = apps.get_model("access", "Permission")

    view = Permission.objects.get(code="attachments.view")
    manage = Permission.objects.get(code="attachments.manage")

    for role in Role.objects.filter(name__in=["Owner", "Accountant", "Sales"], is_system=True):
        role.permissions.add(view, manage)
    for role in Role.objects.filter(name="Viewer", is_system=True):
        role.permissions.add(view)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("access", "0009_seed_approvals_permissions"),
    ]

    operations = [
        migrations.RunPython(seed_new_permissions, noop),
        migrations.RunPython(backfill_existing_roles, noop),
    ]
