# Sprint 4.4 — see 0009's note: split into its own migration/transaction
# to avoid a Postgres "cannot CREATE INDEX because it has pending
# trigger events" error when combined with the reverses self-FK's
# schema changes.
#
# CRITICAL: status's AddField default (0009) is 'draft', but every
# entry that already exists was created by post_invoice_journal_entry/
# void_invoice_journal_entry, which never had a draft concept — "كل
# قيد يُنشأ 'مُرحَّل' فعليًا فور الإنشاء" (ARCH_REVIEW_1.md §3.2). Leaving
# them at 'draft' would make every historical entry vanish from every
# POSTED-only report (rule 13) the instant 0009 ran — a correctness
# bug, not just cosmetic. They're set to 'posted' here.
#
# content_type/object_id are backfilled from the existing source_type/
# source_id (both currently only ever "invoice"/"invoice_void",
# pointing at sales.Invoice) — source_type/source_id themselves are
# left untouched (superseded, not deleted; see the model docstring).
from django.db import migrations, models


def backfill_status_and_source(apps, schema_editor):
    JournalEntry = apps.get_model("accounting", "JournalEntry")
    ContentType = apps.get_model("contenttypes", "ContentType")

    JournalEntry.objects.all().update(status="posted")

    invoice_ct = ContentType.objects.filter(app_label="sales", model="invoice").first()
    if invoice_ct is not None:
        JournalEntry.objects.filter(
            source_type__in=["invoice", "invoice_void"], source_id__isnull=False
        ).update(content_type=invoice_ct, object_id=models.F("source_id"))


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0010_journal_line_reconciliation_fields"),
    ]

    operations = [
        migrations.RunPython(backfill_status_and_source, noop),
    ]
