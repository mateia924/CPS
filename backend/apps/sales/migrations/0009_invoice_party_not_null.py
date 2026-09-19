import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    # Hand-written (same pattern as 0004_invoice_legal_entity_not_null.py):
    # every existing row is backfilled by 0008 before this runs.

    dependencies = [
        ("sales", "0008_migrate_customers_to_parties"),
    ]

    operations = [
        migrations.AlterField(
            model_name="invoice",
            name="party",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="invoices", to="parties.party"
            ),
        ),
    ]
