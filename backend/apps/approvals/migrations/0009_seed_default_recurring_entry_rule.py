# Sprint 6.4 (decision 9): "قاعدة افتراضية مزروعة min_amount=0 → Owner
# (قابلة للتعديل كقاعدة journal_entry في 4.5)" — same default-rule
# pattern as 0002_seed_default_jv_rule, freely editable/deletable
# afterward (unlike the fixed IBAN_CHANGE/OPENING_BALANCE rules).
from django.db import migrations


def seed_default_recurring_entry_rule(apps, schema_editor):
    # Reads the one shared definition (apps/approvals/defaults.py) that
    # registration also uses, so the two can't drift (7.4 follow-up).
    from apps.approvals.defaults import backfill_default_approval_rules

    backfill_default_approval_rules(apps, ["recurring_entry"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0008_alter_approvalrule_doc_type"),
    ]

    operations = [
        migrations.RunPython(seed_default_recurring_entry_rule, noop),
    ]
