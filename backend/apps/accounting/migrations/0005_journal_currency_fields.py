# Sprint 4.2 (docs/SYSTEM_ANALYSIS.md 3.11/3.15.3): currency/exchange_rate
# on every journal entry and line. Existing rows: "currency =
# legal_entity.base_currency, exchange_rate = 1, *_fc = *" per the
# sprint spec — the AddField defaults (SAR/1/0) are only a safe
# placeholder for the brief window before backfill_currency_fields runs
# in the same migration; a tenant whose legal_entity.base_currency isn't
# SAR would otherwise be silently wrong.

from django.db import migrations, models


def backfill_currency_fields(apps, schema_editor):
    JournalEntry = apps.get_model("accounting", "JournalEntry")
    for entry in JournalEntry.objects.select_related("legal_entity").iterator():
        JournalEntry.objects.filter(pk=entry.pk).update(currency=entry.legal_entity.base_currency)
        entry.lines.update(debit_fc=models.F("debit"), credit_fc=models.F("credit"))


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounting', '0004_journalentry_legal_entity_not_null'),
    ]

    operations = [
        migrations.AddField(
            model_name='journalentry',
            name='currency',
            field=models.CharField(default='SAR', max_length=3, verbose_name='currency'),
        ),
        migrations.AddField(
            model_name='journalentry',
            name='exchange_rate',
            field=models.DecimalField(decimal_places=8, default=1, max_digits=18, verbose_name='exchange rate'),
        ),
        migrations.AddField(
            model_name='journalline',
            name='credit_fc',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
        migrations.AddField(
            model_name='journalline',
            name='debit_fc',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
        migrations.RunPython(backfill_currency_fields, noop),
    ]
