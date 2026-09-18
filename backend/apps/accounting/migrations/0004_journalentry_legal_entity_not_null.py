import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0003_backfill_journalentry_legal_entity"),
    ]

    operations = [
        migrations.AlterField(
            model_name="journalentry",
            name="legal_entity",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="journal_entries",
                to="organization.legalentity",
            ),
        ),
    ]
