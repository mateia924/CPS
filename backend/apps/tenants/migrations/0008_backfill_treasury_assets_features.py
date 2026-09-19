from django.db import migrations

# Sprint 3: TenantFeatures.treasury/assets were added with default=False
# (0007), so every existing tenant currently shows them off regardless
# of plan. Re-sync from each tenant's current plan right away — same
# effect as apps.tenants.services.apply_plan_to_tenant, without
# importing live app code from a migration.


def backfill(apps, schema_editor):
    TenantFeatures = apps.get_model("tenants", "TenantFeatures")
    for features in TenantFeatures.objects.select_related("tenant__plan").all():
        plan = features.tenant.plan
        if plan is None:
            continue
        features.treasury = plan.feature_treasury
        features.assets = plan.feature_assets
        features.save(update_fields=["treasury", "assets"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0007_tenantfeatures_assets_tenantfeatures_treasury"),
        ("platform", "0005_seed_sprint3_plan_flags"),
    ]

    operations = [
        migrations.RunPython(backfill, noop),
    ]
