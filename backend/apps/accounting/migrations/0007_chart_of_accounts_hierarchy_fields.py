# Sprint 4.3 (docs/SYSTEM_ANALYSIS.md 3.4; ARCH_REVIEW_1.md §3.1):
# hierarchical chart of accounts. normal_balance's AddField default ('')
# is only a placeholder for the instant before backfill_normal_balance
# runs in this same migration.

import django.db.models.deletion
from django.db import migrations, models


def backfill_normal_balance(apps, schema_editor):
    Account = apps.get_model("accounting", "Account")
    defaults = {"asset": "debit", "expense": "debit", "liability": "credit", "equity": "credit", "revenue": "credit"}
    for type_, normal_balance in defaults.items():
        Account.objects.filter(type=type_).update(normal_balance=normal_balance)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounting', '0006_backfill_fx_rounding_account'),
        ('parties', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='account',
            name='allow_posting',
            field=models.BooleanField(default=True, verbose_name='allow posting'),
        ),
        migrations.AddField(
            model_name='account',
            name='is_active',
            field=models.BooleanField(default=True, verbose_name='active'),
        ),
        migrations.AddField(
            model_name='account',
            name='is_intercompany',
            field=models.BooleanField(default=False, verbose_name='intercompany'),
        ),
        migrations.AddField(
            model_name='account',
            name='level',
            field=models.PositiveIntegerField(default=0, editable=False),
        ),
        migrations.AddField(
            model_name='account',
            name='normal_balance',
            field=models.CharField(blank=True, choices=[('debit', 'Debit'), ('credit', 'Credit')], default='', max_length=10, verbose_name='normal balance'),
        ),
        migrations.AddField(
            model_name='account',
            name='parent',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='children', to='accounting.account'),
        ),
        migrations.AddField(
            model_name='account',
            name='party',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='gl_accounts', to='parties.party'),
        ),
        migrations.AddField(
            model_name='account',
            name='system_key',
            field=models.CharField(blank=True, default='', max_length=30, verbose_name='system key'),
        ),
        migrations.AddField(
            model_name='journalline',
            name='party',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='journal_lines', to='parties.party'),
        ),
        migrations.RunPython(backfill_normal_balance, noop),
    ]
