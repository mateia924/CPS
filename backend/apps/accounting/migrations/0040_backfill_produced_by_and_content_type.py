# Sprint 7.2.7 (§8.7, owner decision 2026-10-06): produced_by <-
# source_type, verbatim, for every row that has one (82 rows on live
# at the time this was written: the 24 "old-only" plus the 58 already
# dual-written with content_type/object_id — those 58 need produced_by
# too, they never had it).
#
# Deliberately idempotent (dry-report §8.7 test requirement): re-
# running this is a safe no-op for rows already carrying the target
# value.
#
# REMOVED 2026-10-07 (owner decision, after a real failure on
# staging): this migration originally had a second part ("نقل ب") —
# backfilling content_type/object_id for the four old-only rows that
# never got either mechanism's reference half (asset_disposal x2,
# opening_balance x1, asset_disposal_correction x1). It was a direct
# .update(content_type=..., object_id=...) against existing
# JournalEntry rows. For any row already POSTED — which is virtually
# all of them, these are terminal, audited documents — that is an
# UPDATE on a posted journal entry, something this project forbids
# categorically and has since 0019_posted_entry_protection_triggers
# (SYSTEM_ANALYSIS.md, 2026-09-23 decision: no field on a POSTED entry
# is ever modified directly, not even incidentally; a correction is a
# reversal and a new posting, never a direct update). The trigger
# (protect_posted_journal_entry()) caught this on staging's real,
# live-shaped data with a ProgrammingError — dev's own data has no
# POSTED row matching those three source_type values with content_type
# still null, so it silently ran as a no-op there and the bug was
# invisible until the step-4 staging walkthrough (replacing a 24-hour
# time-based wait with this exact kind of real check is what caught
# it — see §11, 2026-10-07).
#
# The trigger did not reject a valid migration; it rejected an
# operation this project had already forbidden itself from doing. The
# correct fix is not a workaround around the trigger (disabling it,
# even for one migration, is itself forbidden — §0 rule 1) but
# abandoning transfer ب entirely: these four rows' content_type/
# object_id stay permanently null, exactly like recurring's 20/86 rows
# already do (recurring was excluded from transfer ب from the start,
# for an unrelated reason — it just happened to sidestep this same
# trigger). produced_by (this migration's own transfer أ, unaffected —
# it only ever touches produced_by/source_type, never an already-
# posted row's content_type/object_id) plus the frozen source_type/
# source_id trail are the only record of what these old rows were.
from django.db import migrations
from django.db.models import F


def backfill(apps, schema_editor):
    JournalEntry = apps.get_model("accounting", "JournalEntry")
    JournalEntry.objects.exclude(source_type="").update(produced_by=F("source_type"))


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0039_journalentry_produced_by"),
    ]

    operations = [
        migrations.RunPython(backfill, noop),
    ]
