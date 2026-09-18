import uuid

from django.db import migrations


def backfill_default_entities(apps, schema_editor):
    """For every tenant that existed before this sprint (and so has no
    legal entity yet), create a default COMPANY + BRANCH under it — same
    shape apps.accounts.serializers.RegisterSerializer now creates
    inline for brand-new tenants. Invoices/journal entries are backfilled
    onto the new branch by the sales/accounting apps' own data
    migrations, which depend on this one having run first.
    """
    Tenant = apps.get_model("tenants", "Tenant")
    LegalEntity = apps.get_model("organization", "LegalEntity")

    for tenant in Tenant.objects.all():
        if LegalEntity.objects.filter(tenant=tenant).exists():
            continue
        company = LegalEntity.objects.create(
            id=uuid.uuid4(),
            tenant=tenant,
            code="MAIN",
            name=tenant.name,
            entity_type="company",
            country_code="SA",
            base_currency="SAR",
        )
        LegalEntity.objects.create(
            id=uuid.uuid4(),
            tenant=tenant,
            code="MAIN-01",
            name="Main Branch",
            entity_type="branch",
            parent=company,
            country_code="SA",
            base_currency="SAR",
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("organization", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(backfill_default_entities, noop),
    ]
