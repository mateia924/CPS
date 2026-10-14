# Sprint 7.0 (D5): "ApprovalRule لأنواع STOCK_RECEIPT, STOCK_ISSUE,
# STOCK_TRANSFER, STOCK_COUNT بقاعدة افتراضية min_amount=0 → Owner
# قابلة للتعديل" — same default-rule pattern as 0009/0011/0013/0015,
# freely editable/deletable afterward (not in any locked-doc-types set).
from django.db import migrations

_DOC_TYPES = ["stock_receipt", "stock_issue", "stock_transfer", "stock_count"]


def seed_default_stock_document_rules(apps, schema_editor):
    # Reads the one shared definition (apps/approvals/defaults.py) that
    # registration also uses, so the two can't drift (7.4 follow-up).
    from apps.approvals.defaults import backfill_default_approval_rules

    backfill_default_approval_rules(apps, _DOC_TYPES)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0018_alter_approvalrule_doc_type"),
    ]

    operations = [
        migrations.RunPython(seed_default_stock_document_rules, noop),
    ]
