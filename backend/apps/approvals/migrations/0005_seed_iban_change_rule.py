# Sprint 5.5 (block 5.5.0, CFO_REVIEW_1 C10): 3.15.9 requires approval
# on every IBAN change with no amount threshold — every tenant gets a
# fixed doc_type=iban_change rule (min_amount=0, required_role=Owner).
# Unlike the journal_entry default rule (0002), this one is not meant
# to be editable/deletable from the "قواعد الاعتماد" screen — see
# ApprovalRuleViewSet.
from django.db import migrations


def seed_iban_change_rule(apps, schema_editor):
    # Reads the one shared definition (apps/approvals/defaults.py) that
    # registration also uses, so the two can't drift (7.4 follow-up).
    from apps.approvals.defaults import backfill_default_approval_rules

    backfill_default_approval_rules(apps, ["iban_change"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0004_iban_change_request"),
    ]

    operations = [
        migrations.RunPython(seed_iban_change_rule, noop),
    ]
