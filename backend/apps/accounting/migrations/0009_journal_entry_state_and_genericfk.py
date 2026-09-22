# Sprint 4.4 (docs/SYSTEM_ANALYSIS.md 3.15.1; ARCH_REVIEW_1.md §3.2/
# debt #4/#6): JournalEntry status + a real GenericFK source — schema
# only. The critical status/content_type data backfill is a SEPARATE
# migration (0011_backfill_journal_entry_status_and_source.py): doing
# it in this same transaction hit a genuine Postgres restriction
# ("cannot CREATE INDEX because it has pending trigger events") —
# adding the self-referential `reverses` FK and then, in the same
# transaction, writing to the `content_type` FK column trips Postgres's
# deferred-constraint-trigger machinery. Splitting the data migration
# into its own transaction (and its own migration file) is the
# standard fix.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounting', '0008_tag_existing_accounts_with_system_keys'),
        ('contenttypes', '0002_remove_content_type_name'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='journalentry',
            name='content_type',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='contenttypes.contenttype'),
        ),
        migrations.AddField(
            model_name='journalentry',
            name='created_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='journalentry',
            name='number',
            field=models.CharField(blank=True, default='', max_length=32, verbose_name='number'),
        ),
        migrations.AddField(
            model_name='journalentry',
            name='object_id',
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='journalentry',
            name='reference',
            field=models.CharField(blank=True, max_length=100, verbose_name='reference'),
        ),
        migrations.AddField(
            model_name='journalentry',
            name='reverses',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='reversed_by', to='accounting.journalentry'),
        ),
        migrations.AddField(
            model_name='journalentry',
            name='status',
            field=models.CharField(choices=[('draft', 'Draft'), ('pending_approval', 'Pending approval'), ('approved', 'Approved'), ('posted', 'Posted'), ('reversed', 'Reversed')], default='draft', max_length=20),
        ),
    ]
