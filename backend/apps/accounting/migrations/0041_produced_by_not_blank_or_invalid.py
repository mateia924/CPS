# Sprint 7.2.7 (§8.7, owner decision 2026-10-07): produced_by becomes
# non-blank and enum-restricted. Three operations, strictly ordered —
# the backfill MUST run before the constraint is added, or the
# constraint fails immediately against any existing blank row (every
# genuinely manual entry created before this migration, on dev or any
# other environment this has already reached):
#
#   1. RunPython: every row with produced_by="" (a genuine manual
#      entry, or a reversal of one — see apps.accounting.services.
#      create_manual_journal_entry/reverse_journal_entry) gets
#      produced_by="manual" explicitly. Idempotent — re-running finds
#      no more blank rows the second time.
#   2. AlterField: choices=ProducedBy.choices (validation-only, for
#      forms/admin/full_clean — never DB-enforced by itself).
#   3. AddConstraint: the actual enforcement. One CheckConstraint
#      restricting the column to the declared enum values — this is
#      simultaneously "never blank" (empty string isn't a declared
#      member) and "never invented" (same reasoning the owner's own
#      message states explicitly). Not two separate SQL constraints:
#      on a CharField, Django's own empty-string default for an
#      omitted value means a literal SQL NOT NULL would be trivially
#      satisfied by "" and catch nothing — this one constraint is what
#      actually does both jobs.
from django.db import migrations, models


def backfill_manual(apps, schema_editor):
    JournalEntry = apps.get_model("accounting", "JournalEntry")
    JournalEntry.objects.filter(produced_by="").update(produced_by="manual")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0040_backfill_produced_by_and_content_type"),
    ]

    operations = [
        migrations.RunPython(backfill_manual, noop),
        migrations.AlterField(
            model_name="journalentry",
            name="produced_by",
            field=models.CharField(
                choices=[
                    ("recurring", "Recurring entry"),
                    ("voucher_payment", "Payment voucher"),
                    ("voucher_receipt", "Receipt voucher"),
                    ("voucher_settlement", "Settlement voucher"),
                    ("invoice", "Invoice"),
                    ("invoice_void", "Invoice void"),
                    ("asset_disposal", "Asset disposal"),
                    ("asset_disposal_correction", "Asset disposal correction"),
                    ("opening_balance", "Opening balance"),
                    ("manual", "Manual"),
                ],
                max_length=50,
                verbose_name="produced by",
            ),
        ),
        migrations.AddConstraint(
            model_name="journalentry",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    produced_by__in=[
                        "recurring",
                        "voucher_payment",
                        "voucher_receipt",
                        "voucher_settlement",
                        "invoice",
                        "invoice_void",
                        "asset_disposal",
                        "asset_disposal_correction",
                        "opening_balance",
                        "manual",
                    ]
                ),
                name="accounting_journalentry_produced_by_valid",
            ),
        ),
    ]
