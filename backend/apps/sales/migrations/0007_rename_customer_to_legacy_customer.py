import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    # Hand-written (avoids makemigrations' interactive rename prompt,
    # which can't be answered non-interactively): sprint 3 supersedes
    # Invoice.customer with Invoice.party (parties.Party) — the old FK
    # is renamed and made nullable, not dropped, so no data is lost. See
    # docs/SYSTEM_ANALYSIS.md Decision Log.

    dependencies = [
        ("sales", "0006_invoice_party"),
    ]

    operations = [
        migrations.RenameField(
            model_name="invoice", old_name="customer", new_name="legacy_customer"
        ),
        migrations.AlterField(
            model_name="invoice",
            name="legacy_customer",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="invoices", to="sales.customer",
            ),
        ),
    ]
