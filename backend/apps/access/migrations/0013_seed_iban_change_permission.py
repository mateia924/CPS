from django.db import migrations

# Kept in sync by hand with apps.access.services.DEFAULT_PERMISSIONS —
# see 0003_seed_permissions.py's note about not importing live app code.
# Sprint 5.5 (block 5.5.0, CFO_REVIEW_1 C10).
NEW_PERMISSIONS = [
    ("treasury.request_iban_change", "Request an IBAN change for a bank or supplier"),
]


def seed_new_permissions(apps, schema_editor):
    Permission = apps.get_model("access", "Permission")
    for code, description in NEW_PERMISSIONS:
        Permission.objects.update_or_create(code=code, defaults={"description": description})


def backfill_existing_roles(apps, schema_editor):
    """Owner (grants every permission per SYSTEM_ROLES, but each
    tenant's Owner row is a materialized snapshot from creation time —
    same backfill need as every prior seed-permission migration) and
    Accountant (the role that actually creates the request; approval
    itself is gated by the fixed IBAN_CHANGE ApprovalRule, not a
    permission)."""
    Role = apps.get_model("access", "Role")
    Permission = apps.get_model("access", "Permission")

    permission = Permission.objects.get(code="treasury.request_iban_change")
    for role in Role.objects.filter(name__in=["Owner", "Accountant"], is_system=True):
        role.permissions.add(permission)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("access", "0012_seed_control_account_override_permission"),
    ]

    operations = [
        migrations.RunPython(seed_new_permissions, noop),
        migrations.RunPython(backfill_existing_roles, noop),
    ]
