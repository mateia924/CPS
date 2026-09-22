# Correction after sprint 4.1 (Decision Log, SYSTEM_ANALYSIS.md §11):
# reverts the invoice-number uniqueness constraint back to tenant-wide
# — ZATCA requires a unique number per tax registration, and branches
# normally share one tax number, so per-legal_entity uniqueness (0010)
# was wrong. No existing data violates this (checked: zero duplicate
# (tenant, number) pairs before applying).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('organization', '0002_backfill_default_entities'),
        ('parties', '0001_initial'),
        ('sales', '0011_invoice_currency_fields'),
        ('tenants', '0009_tenant_business_type'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='invoice',
            name='unique_invoice_number_per_tenant_and_entity',
        ),
        migrations.AddConstraint(
            model_name='invoice',
            constraint=models.UniqueConstraint(fields=('tenant', 'number'), name='unique_invoice_number_per_tenant'),
        ),
    ]
