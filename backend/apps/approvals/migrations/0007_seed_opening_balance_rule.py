# Sprint 6.3 (decision 8): 3.16.3 requires Owner approval on every
# opening balance with no amount threshold — every tenant gets a fixed
# doc_type=opening_balance rule (min_amount=0, required_role=Owner),
# same pattern as 0005_seed_iban_change_rule. Not meant to be editable/
# deletable from "قواعد الاعتماد" — see ApprovalRuleViewSet.
from django.db import migrations


def seed_opening_balance_rule(apps, schema_editor):
    # Reads the one shared definition (apps/approvals/defaults.py) that
    # registration also uses, so the two can't drift (7.4 follow-up).
    from apps.approvals.defaults import backfill_default_approval_rules

    backfill_default_approval_rules(apps, ["opening_balance"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0006_alter_approvalrule_doc_type"),
    ]

    operations = [
        migrations.RunPython(seed_opening_balance_rule, noop),
    ]
