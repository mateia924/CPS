import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0003_backfill_invoice_legal_entity"),
    ]

    operations = [
        migrations.AlterField(
            model_name="invoice",
            name="legal_entity",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="invoices",
                to="organization.legalentity",
            ),
        ),
    ]
