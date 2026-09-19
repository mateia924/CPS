from django.db import migrations

# Kept in sync by hand with apps.access.services.DEFAULT_PERMISSIONS —
# see 0003_seed_permissions.py's note about not importing live app code.
# Sprint 3 (3.3): parties.* supersedes customers.* for the unified Party
# screen; customers.* stays in the catalog, unused, never deleted.
NEW_PERMISSIONS = [
    ("parties.view", "View parties (customers, suppliers, employees, affiliates)"),
    ("parties.manage", "Create, edit and deactivate parties and their roles"),
    ("treasury.view", "View banks, cash boxes and custodies"),
    ("treasury.manage", "Create, edit and deactivate banks, cash boxes and custodies"),
    ("assets.view", "View fixed assets"),
    ("assets.manage", "Create, edit and deactivate fixed assets"),
]


def seed_new_permissions(apps, schema_editor):
    Permission = apps.get_model("access", "Permission")
    for code, description in NEW_PERMISSIONS:
        Permission.objects.update_or_create(code=code, defaults={"description": description})


def backfill_existing_roles(apps, schema_editor):
    """Additive-only (grants, never revokes): every existing Role that
    already had customers.view/customers.manage also gets the new
    parties.view/parties.manage — the unified Party screen replaces the
    old Customer screen, so a role that could manage customers before
    must still be able to after this sprint. Owner (permissions=None at
    seed time) also needs an explicit grant here since its Role row
    already exists with the old, fixed set of permissions.

    treasury.*/assets.* have no prior equivalent, so they're granted by
    system-role name directly, mirroring apps.access.services.SYSTEM_ROLES:
    Owner gets everything, Accountant/Viewer get view-only, Sales gets
    neither (doesn't need bank/asset visibility).
    """
    Role = apps.get_model("access", "Role")
    Permission = apps.get_model("access", "Permission")

    def perm(code):
        return Permission.objects.get(code=code)

    customers_manage_roles = Role.objects.filter(permissions__code="customers.manage")
    for role in customers_manage_roles:
        role.permissions.add(perm("parties.manage"))

    customers_view_roles = Role.objects.filter(permissions__code="customers.view")
    for role in customers_view_roles:
        role.permissions.add(perm("parties.view"))

    owner_roles = Role.objects.filter(name="Owner", is_system=True)
    for role in owner_roles:
        role.permissions.add(
            perm("parties.view"), perm("parties.manage"),
            perm("treasury.view"), perm("treasury.manage"),
            perm("assets.view"), perm("assets.manage"),
        )

    view_only_roles = Role.objects.filter(name__in=["Accountant", "Viewer"], is_system=True)
    for role in view_only_roles:
        role.permissions.add(perm("treasury.view"), perm("assets.view"))


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("access", "0004_backfill_tenant_roles"),
    ]

    operations = [
        migrations.RunPython(seed_new_permissions, noop),
        migrations.RunPython(backfill_existing_roles, noop),
    ]
