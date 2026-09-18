from django.db import migrations

# Kept in sync by hand with apps.access.services.DEFAULT_PERMISSIONS.
# Migrations must not import live app code (models/services can drift
# from the schema this migration was written against), so the catalog
# is duplicated here as plain strings rather than imported.
PERMISSIONS = [
    ("customers.view", "View customers"),
    ("customers.manage", "Create, edit and delete customers"),
    ("products.view", "View products"),
    ("products.manage", "Create, edit and delete products"),
    ("invoices.view", "View invoices"),
    ("invoices.create", "Create invoices"),
    ("invoices.approve", "Issue/approve invoices"),
    ("accounting.view", "View the chart of accounts and journal entries"),
    ("organization.view", "View legal entities"),
    ("organization.manage", "Create, edit and deactivate legal entities"),
    ("costcenters.view", "View cost centers"),
    ("costcenters.manage", "Create, edit and deactivate cost centers"),
    ("roles.manage", "Manage roles, permissions and user assignments"),
]


def seed_permissions(apps, schema_editor):
    Permission = apps.get_model("access", "Permission")
    for code, description in PERMISSIONS:
        Permission.objects.update_or_create(code=code, defaults={"description": description})


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("access", "0002_initial"),
    ]

    operations = [
        migrations.RunPython(seed_permissions, noop),
    ]
