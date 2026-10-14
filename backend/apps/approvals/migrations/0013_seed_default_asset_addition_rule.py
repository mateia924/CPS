# Sprint 6.5 (decision 11): "قاعدة افتراضية مزروعة min_amount=0 → Owner
# (قابلة للتعديل)" — same default-rule pattern as
# 0011_seed_default_asset_depreciation_rule.
from django.db import migrations


def seed_default_asset_addition_rule(apps, schema_editor):
    # Reads the one shared definition (apps/approvals/defaults.py) that
    # registration also uses, so the two can't drift (7.4 follow-up).
    from apps.approvals.defaults import backfill_default_approval_rules

    backfill_default_approval_rules(apps, ["asset_addition"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0012_asset_addition_doc_type"),
    ]

    operations = [
        migrations.RunPython(seed_default_asset_addition_rule, noop),
    ]
