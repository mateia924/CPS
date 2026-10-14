# Sprint 6.5 (decision 11): "قاعدة افتراضية مزروعة min_amount=0 → Owner
# (قابلة للتعديل)" — same default-rule pattern as
# 0013_seed_default_asset_addition_rule.
from django.db import migrations


def seed_default_asset_disposal_rule(apps, schema_editor):
    # Reads the one shared definition (apps/approvals/defaults.py) that
    # registration also uses, so the two can't drift (7.4 follow-up).
    from apps.approvals.defaults import backfill_default_approval_rules

    backfill_default_approval_rules(apps, ["asset_disposal"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0014_asset_disposal_doc_type"),
    ]

    operations = [
        migrations.RunPython(seed_default_asset_disposal_rule, noop),
    ]
