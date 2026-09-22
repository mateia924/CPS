# Sprint 4.2 (docs/SYSTEM_ANALYSIS.md 3.11/3.15.3): currency/exchange_rate
# /base_total on every invoice. Existing rows: "currency =
# legal_entity.base_currency, exchange_rate = 1, *_fc = *" (no *_fc on
# InvoiceLine — see the Decision Log — so here that's just base_total =
# total). The AddField defaults (SAR/1/0) are only a safe placeholder
# for the brief window before backfill runs in the same migration.

from django.db import migrations, models


def backfill_currency_fields(apps, schema_editor):
    Invoice = apps.get_model("sales", "Invoice")
    for invoice in Invoice.objects.select_related("legal_entity").iterator():
        Invoice.objects.filter(pk=invoice.pk).update(
            currency=invoice.legal_entity.base_currency, base_total=invoice.total
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0010_invoice_number_unique_per_legal_entity'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoice',
            name='base_total',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14, verbose_name='base total'),
        ),
        migrations.AddField(
            model_name='invoice',
            name='currency',
            field=models.CharField(default='SAR', max_length=3, verbose_name='currency'),
        ),
        migrations.AddField(
            model_name='invoice',
            name='exchange_rate',
            field=models.DecimalField(decimal_places=8, default=1, max_digits=18, verbose_name='exchange rate'),
        ),
        migrations.RunPython(backfill_currency_fields, noop),
    ]
