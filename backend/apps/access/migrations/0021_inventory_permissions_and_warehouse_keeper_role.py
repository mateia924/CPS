from django.db import migrations

# Kept in sync by hand with apps.access.services.DEFAULT_PERMISSIONS —
# see 0003_seed_permissions.py's note about not importing live app code.
# Sprint 7.0 (D17).
NEW_PERMISSIONS = [
    ("inventory.view", "View items, warehouses and stock documents"),
    ("inventory.manage", "Create and edit items, warehouses and inventory settings"),
    ("inventory.post", "Post stock receipt/issue/transfer/count documents and confirm transfers"),
]

# D17: "المالك الكل؛ المحاسب inventory.view + inventory.post" —
# Accountant deliberately gets no inventory.manage (creating/editing
# items and warehouses is the warehouse keeper's job, same split
# accounting.manage/accounting.post_control_accounts already draws
# elsewhere).
ROLE_GRANTS = {
    "inventory.view": ["Owner", "Accountant"],
    "inventory.manage": ["Owner"],
    "inventory.post": ["Owner", "Accountant"],
}

# D17: new system role "أمين مستودع" — inventory.view/manage/post plus
# accounting.view for the stock reports/reconciliation screens only
# (no accounting.manage, no journal-entry access).
WAREHOUSE_KEEPER_PERMISSIONS = ["inventory.view", "inventory.manage", "inventory.post", "accounting.view"]


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


def create_warehouse_keeper_role(apps, schema_editor):
    """For every tenant that already exists (no role of this name yet
    — a brand-new tenant gets it from apps.access.services.
    seed_default_roles instead), create the new system role with its
    default permission set. Idempotent: a re-run finds the role
    already there and does nothing."""
    Tenant = apps.get_model("tenants", "Tenant")
    Role = apps.get_model("access", "Role")
    Permission = apps.get_model("access", "Permission")

    permissions = Permission.objects.filter(code__in=WAREHOUSE_KEEPER_PERMISSIONS)
    for tenant in Tenant.objects.all().iterator():
        if Role.objects.filter(tenant=tenant, name="Warehouse Keeper", is_system=True).exists():
            continue
        role = Role.objects.create(tenant=tenant, name="Warehouse Keeper", is_system=True)
        role.permissions.set(permissions)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("access", "0020_role_deleted_at_role_deleted_by"),
    ]

    operations = [
        migrations.RunPython(seed_new_permissions, noop),
        migrations.RunPython(backfill_existing_roles, noop),
        migrations.RunPython(create_warehouse_keeper_role, noop),
    ]
