# Sprint 4.6 (3.16.2, rule 16): final step of the 3-step safe migration
# (nullable in 0014, backfilled in 0015, NOT NULL here) — same pattern
# as Invoice.legal_entity's own history. Verified zero remaining NULL
# rows on the real dev database before writing this.
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0015_backfill_invoice_line_tax_code"),
    ]

    operations = [
        migrations.AlterField(
            model_name="invoiceline",
            name="tax_code",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="invoice_lines",
                to="accounting.taxcode",
            ),
        ),
    ]
