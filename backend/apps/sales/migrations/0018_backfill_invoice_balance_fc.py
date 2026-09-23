from django.db import migrations


def backfill(apps, schema_editor):
    """Sprint 5.0 (prompt block 5.0 item 5, corrected per owner review):
    "الفواتير الحالية: UNPAID والرصيد = الإجمالي" — but only for an
    invoice that's actually still open. A CANCELLED (voided) invoice, or
    one whose posted journal entry was later reversed, must not show a
    balance_fc > 0: it would look like an open receivable in the 5.4
    statements/aging report, when in fact nothing is owed. paid_fc stays
    0 for every pre-5.0 row either way — nothing could have been
    allocated before VoucherAllocation exists.
    """
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE sales_invoice
            SET balance_fc = total, paid_fc = 0
            WHERE status <> 'cancelled'
              AND id NOT IN (
                  SELECT source_id FROM accounting_journalentry
                  WHERE source_type = 'invoice' AND status = 'reversed' AND source_id IS NOT NULL
              )
            """
        )
        cursor.execute(
            """
            UPDATE sales_invoice
            SET balance_fc = 0, paid_fc = 0
            WHERE status = 'cancelled'
               OR id IN (
                  SELECT source_id FROM accounting_journalentry
                  WHERE source_type = 'invoice' AND status = 'reversed' AND source_id IS NOT NULL
               )
            """
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0017_voucher_fields_and_payment_tracking"),
    ]

    operations = [
        migrations.RunPython(backfill, noop),
    ]
