from django.db import migrations


def backfill_tenant_features(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    TenantFeatures = apps.get_model("tenants", "TenantFeatures")

    for tenant in Tenant.objects.all():
        TenantFeatures.objects.get_or_create(
            tenant=tenant,
            defaults={
                "organization": True,
                "cost_centers": True,
                "inventory": False,
                "purchasing": False,
                "hr": False,
            },
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0002_tenantfeatures"),
    ]

    operations = [
        migrations.RunPython(backfill_tenant_features, noop),
    ]
