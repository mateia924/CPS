# Sprint 6.5.15 (UAT item 1): a DB-level uniqueness guarantee for
# JournalEntry.number, tenant-wide — the exact protection Invoice/
# Voucher already had (see their own migration history) that
# JournalEntry never got. Existing duplicates (the real, live "JV-2026-
# 00001" issued on both a simplified-mode tenant's company and branch,
# from before apps.numbering.services' sequence-merge fix) are flagged
# legacy_duplicate_number=True — grandfathered, never renumbered or
# otherwise touched — so the constraint below can be added at all
# without failing, and so this can never silently recur unflagged.
from django.conf import settings
from django.db import migrations, models


def flag_duplicate_journal_entry_numbers(apps, schema_editor):
    JournalEntry = apps.get_model("accounting", "JournalEntry")

    report = []
    duplicate_groups = (
        JournalEntry.objects.exclude(number="")
        .values("tenant_id", "number")
        .annotate(count=models.Count("id"))
        .filter(count__gt=1)
    )
    for group in duplicate_groups:
        entries = list(
            JournalEntry.objects.filter(tenant_id=group["tenant_id"], number=group["number"]).order_by("created_at", "id")
        )
        # Keep the earliest as the canonical, unflagged row; flag every
        # later one — this is metadata only (a dedup marker), never a
        # change to number/date/amount/status on any of them.
        for entry in entries[1:]:
            entry.legacy_duplicate_number = True
            entry.save(update_fields=["legacy_duplicate_number"])
        report.append(
            {"tenant_id": str(group["tenant_id"]), "number": group["number"], "flagged": len(entries) - 1}
        )

    print(f"[sprint 6.5.15 item 1] flagged legacy duplicate JournalEntry numbers: {report}")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounting', '0028_fixed_assets_allow_manual_posting'),
        ('contenttypes', '0002_remove_content_type_name'),
        ('organization', '0005_legalentity_opening_approved_at'),
        ('tenants', '0014_tenant_default_legal_entity'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='journalentry',
            name='legacy_duplicate_number',
            field=models.BooleanField(default=False, verbose_name='legacy duplicate number'),
        ),
        migrations.RunPython(flag_duplicate_journal_entry_numbers, noop),
        migrations.AddConstraint(
            model_name='journalentry',
            constraint=models.UniqueConstraint(condition=models.Q(models.Q(('number', ''), _negated=True), ('legacy_duplicate_number', False)), fields=('tenant', 'number'), name='unique_journal_entry_number_per_tenant'),
        ),
    ]
