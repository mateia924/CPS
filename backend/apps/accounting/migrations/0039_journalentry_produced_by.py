# Sprint 7.2.7 (§8.7, owner decision 2026-10-06): schema-only — adds
# the new field blank for every existing row. The actual data transfer
# (source_type -> produced_by, plus content_type/object_id for the
# four rows that never got it) is the next migration, deliberately
# separate so each is independently reviewable/revertible.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounting', '0038_fiscalyear_deleted_at_fiscalyear_deleted_by'),
    ]

    operations = [
        migrations.AddField(
            model_name='journalentry',
            name='produced_by',
            field=models.CharField(blank=True, max_length=50, verbose_name='produced by'),
        ),
    ]
