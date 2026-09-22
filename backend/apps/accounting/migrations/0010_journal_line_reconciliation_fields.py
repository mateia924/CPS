# Sprint 4.4 (docs/SYSTEM_ANALYSIS.md 3.15.2): bank-reconciliation
# fields on JournalLine — schema only, see BankStatement/
# BankStatementLine's docstrings.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounting', '0009_journal_entry_state_and_genericfk'),
        ('treasury', '0003_bankstatement_bankstatementline'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='journalline',
            name='bank_statement_line',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='journal_lines', to='treasury.bankstatementline'),
        ),
        migrations.AddField(
            model_name='journalline',
            name='description',
            field=models.CharField(blank=True, max_length=255, verbose_name='description'),
        ),
        migrations.AddField(
            model_name='journalline',
            name='reconciled_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='reconciled at'),
        ),
        migrations.AddField(
            model_name='journalline',
            name='reconciled_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL),
        ),
    ]
