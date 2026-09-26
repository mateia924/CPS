# Sprint 6.5 (decision 11): "قاعدة افتراضية مزروعة min_amount=0 → Owner
# (قابلة للتعديل)" — same default-rule pattern as
# 0013_seed_default_asset_addition_rule.
from django.db import migrations


def seed_default_asset_disposal_rule(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    Role = apps.get_model("access", "Role")
    ApprovalRule = apps.get_model("approvals", "ApprovalRule")

    for tenant in Tenant.objects.all().iterator():
        owner_role = Role.objects.filter(tenant=tenant, name="Owner", is_system=True).first()
        if owner_role is None:
            continue
        ApprovalRule.objects.get_or_create(
            tenant=tenant,
            doc_type="asset_disposal",
            min_amount=0,
            defaults={"required_role": owner_role, "is_active": True},
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0014_asset_disposal_doc_type"),
    ]

    operations = [
        migrations.RunPython(seed_default_asset_disposal_rule, noop),
    ]
