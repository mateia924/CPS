# Sprint 6.5 (decision 11): "قاعدة افتراضية مزروعة min_amount=0 → Owner
# (قابلة للتعديل)" — same default-rule pattern as
# 0009_seed_default_recurring_entry_rule, freely editable/deletable
# afterward.
from django.db import migrations


def seed_default_asset_depreciation_rule(apps, schema_editor):
    # Reads the one shared definition (apps/approvals/defaults.py) that
    # registration also uses, so the two can't drift (7.4 follow-up).
    from apps.approvals.defaults import backfill_default_approval_rules

    backfill_default_approval_rules(apps, ["asset_depreciation"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0010_asset_depreciation_doc_type"),
    ]

    operations = [
        migrations.RunPython(seed_default_asset_depreciation_rule, noop),
    ]
