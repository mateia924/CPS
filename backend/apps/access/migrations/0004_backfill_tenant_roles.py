from django.db import migrations

# Kept in sync by hand with apps.access.services.SYSTEM_ROLES — see the
# note in 0003_seed_permissions.py about not importing live app code.
ALL_PERMISSION_CODES = [
    "customers.view", "customers.manage",
    "products.view", "products.manage",
    "invoices.view", "invoices.create", "invoices.approve",
    "accounting.view",
    "organization.view", "organization.manage",
    "costcenters.view", "costcenters.manage",
    "roles.manage",
]

SYSTEM_ROLES = {
    "Owner": None,
    "Accountant": [
        "customers.view", "products.view",
        "invoices.view", "invoices.create", "invoices.approve",
        "accounting.view", "organization.view", "costcenters.view",
    ],
    "Sales": [
        "customers.view", "customers.manage",
        "products.view",
        "invoices.view", "invoices.create",
    ],
    "Viewer": [
        "customers.view", "products.view", "invoices.view",
        "accounting.view", "organization.view", "costcenters.view",
    ],
}


def backfill_tenant_roles(apps, schema_editor):
    """For every tenant that existed before this sprint (no Role rows
    yet), seed the four system roles and assign the new "Owner" role to
    whichever of its users already carried the legacy role='owner' flag
    from Sprint 0 — same shape RegisterSerializer now does inline for
    brand-new tenants.
    """
    Tenant = apps.get_model("tenants", "Tenant")
    Role = apps.get_model("access", "Role")
    Permission = apps.get_model("access", "Permission")
    User = apps.get_model("accounts", "User")

    for tenant in Tenant.objects.all():
        if Role.objects.filter(tenant=tenant).exists():
            continue

        roles_by_name = {}
        for name, codes in SYSTEM_ROLES.items():
            role = Role.objects.create(tenant=tenant, name=name, is_system=True)
            role.permissions.set(Permission.objects.filter(code__in=(codes or ALL_PERMISSION_CODES)))
            roles_by_name[name] = role

        owner_role = roles_by_name["Owner"]
        for user in User.objects.filter(tenant=tenant, role="owner"):
            user.roles.add(owner_role)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("access", "0003_seed_permissions"),
        ("accounts", "0002_user_roles"),
    ]

    operations = [
        migrations.RunPython(backfill_tenant_roles, noop),
    ]
