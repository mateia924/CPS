# Sprint 7.0 (D5): "ApprovalRule لأنواع STOCK_RECEIPT, STOCK_ISSUE,
# STOCK_TRANSFER, STOCK_COUNT بقاعدة افتراضية min_amount=0 → Owner
# قابلة للتعديل" — same default-rule pattern as 0009/0011/0013/0015,
# freely editable/deletable afterward (not in any locked-doc-types set).
from django.db import migrations

_DOC_TYPES = ["stock_receipt", "stock_issue", "stock_transfer", "stock_count"]


def seed_default_stock_document_rules(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    Role = apps.get_model("access", "Role")
    ApprovalRule = apps.get_model("approvals", "ApprovalRule")

    for tenant in Tenant.objects.all().iterator():
        owner_role = Role.objects.filter(tenant=tenant, name="Owner", is_system=True).first()
        if owner_role is None:
            continue
        for doc_type in _DOC_TYPES:
            ApprovalRule.objects.get_or_create(
                tenant=tenant,
                doc_type=doc_type,
                min_amount=0,
                defaults={"required_role": owner_role, "is_active": True},
            )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0018_alter_approvalrule_doc_type"),
    ]

    operations = [
        migrations.RunPython(seed_default_stock_document_rules, noop),
    ]
