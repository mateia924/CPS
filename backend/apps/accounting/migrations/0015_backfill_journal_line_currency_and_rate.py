from django.db import migrations


def backfill(apps, schema_editor):
    """Sprint 5.0 (docs/prompts/sprint-5.md decision 6): every existing
    JournalLine implicitly used its entry's currency/rate (sprint 4.2
    behavior) — this makes that explicit on the line itself instead of
    leaving the new columns at their generic '' / 1 defaults, which
    would be wrong for any line whose entry wasn't in the tenant's base
    currency (e.g. every USD invoice/JV posted during sprint 4's UAT).
    A cross-table UPDATE...FROM needs raw SQL — the ORM's F-expression
    update() can't reference a joined table's column directly.
    """
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE accounting_journalline AS line
            SET currency = entry.currency,
                exchange_rate = entry.exchange_rate
            FROM accounting_journalentry AS entry
            WHERE line.entry_id = entry.id
            """
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0014_journal_line_currency_and_rate"),
    ]

    operations = [
        migrations.RunPython(backfill, noop),
    ]
