from django.db import migrations

# Kept in sync by hand with apps.access.services.DEFAULT_PERMISSIONS — see
# 0003_seed_permissions.py's note about not importing live app code.
# Sprint 5.3 (3.8): سندات القبض/الصرف/التسوية.
NEW_PERMISSIONS = [
    ("vouchers.view", "View vouchers"),
    ("vouchers.add", "Create and edit draft vouchers"),
    ("vouchers.post", "Submit/post vouchers"),
    ("vouchers.approve", "Approve or reject vouchers pending approval"),
    ("vouchers.reverse", "Reverse a posted voucher"),
]


def seed_new_permissions(apps, schema_editor):
    Permission = apps.get_model("access", "Permission")
    for code, description in NEW_PERMISSIONS:
        Permission.objects.update_or_create(code=code, defaults={"description": description})


def backfill_existing_roles(apps, schema_editor):
    """Owner gets everything (SYSTEM_ROLES: None); Accountant gets the
    full set too (day-to-day accountant work per the control matrix,
    3.15.9: محاسب add/post، مدير حسابات/مالك approve/reverse — Owner
    already covers the second half, Accountant covers both in this
    project's simpler 4-role system since there's no separate "مدير
    حسابات" role); Viewer gets view only."""
    Role = apps.get_model("access", "Role")
    Permission = apps.get_model("access", "Permission")

    all_new = list(Permission.objects.filter(code__in=[c for c, _d in NEW_PERMISSIONS]))
    view_only = Permission.objects.get(code="vouchers.view")

    for role in Role.objects.filter(name__in=["Owner", "Accountant"], is_system=True):
        role.permissions.add(*all_new)
    for role in Role.objects.filter(name="Viewer", is_system=True):
        role.permissions.add(view_only)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("access", "0010_seed_attachment_permissions"),
    ]

    operations = [
        migrations.RunPython(seed_new_permissions, noop),
        migrations.RunPython(backfill_existing_roles, noop),
    ]
