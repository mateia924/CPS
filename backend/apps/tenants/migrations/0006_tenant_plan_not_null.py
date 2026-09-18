import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    # Hand-written (same pattern as sales/0004_invoice_legal_entity_not_null.py
    # from sprint 1): every existing row is backfilled by 0005 before this
    # runs, so there's no interactive default to answer.

    dependencies = [
        ("tenants", "0005_backfill_tenant_plans"),
    ]

    operations = [
        migrations.AlterField(
            model_name="tenant",
            name="plan",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="tenants", to="platform.plan"
            ),
        ),
    ]
