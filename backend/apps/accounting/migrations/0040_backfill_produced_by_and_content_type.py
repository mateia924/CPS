# Sprint 7.2.7 (§8.7, owner decision 2026-10-06): the two-part data
# transfer — (a) source_type's string value to produced_by, verbatim,
# for every row that has one (82 rows on live at the time this was
# written: the 24 "old-only" plus the 58 already dual-written with
# content_type/object_id — those 58 need produced_by too, they never
# had it); (b) content_type/object_id for the four rows that never got
# either mechanism's reference half (asset_disposal x2 -> AssetDisposal,
# opening_balance x1 -> OpeningBalanceEntry, asset_disposal_correction
# x1 -> Asset — NOT a model of the same name; confirmed by reading
# apps/assets/management/commands/fix_disposal_correction.py:64,130,
# which writes source_id=asset.id, not a disposal id).
#
# Deliberately idempotent (dry-report §8.7 test requirement): re-
# running this is a safe no-op for rows already carrying the target
# value — every write below is unconditional on the SOURCE value
# matching, not on the destination being empty, so running it twice
# just re-derives the same result.
from django.db import migrations
from django.db.models import F


def backfill(apps, schema_editor):
    JournalEntry = apps.get_model("accounting", "JournalEntry")
    ContentType = apps.get_model("contenttypes", "ContentType")

    # (a) produced_by <- source_type, verbatim, for every row with one.
    JournalEntry.objects.exclude(source_type="").update(produced_by=F("source_type"))

    # (b) content_type/object_id for the four rows missing the
    # reference half entirely.
    asset_disposal_ct = ContentType.objects.get_for_model(apps.get_model("assets", "AssetDisposal"))
    opening_balance_ct = ContentType.objects.get_for_model(apps.get_model("accounting", "OpeningBalanceEntry"))
    asset_ct = ContentType.objects.get_for_model(apps.get_model("assets", "Asset"))

    JournalEntry.objects.filter(source_type="asset_disposal", content_type__isnull=True).update(
        content_type=asset_disposal_ct, object_id=F("source_id")
    )
    JournalEntry.objects.filter(source_type="opening_balance", content_type__isnull=True).update(
        content_type=opening_balance_ct, object_id=F("source_id")
    )
    JournalEntry.objects.filter(source_type="asset_disposal_correction", content_type__isnull=True).update(
        content_type=asset_ct, object_id=F("source_id")
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0039_journalentry_produced_by"),
    ]

    operations = [
        migrations.RunPython(backfill, noop),
    ]
