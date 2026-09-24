# Sprint 6.3 (decision 8): 3.16.3 requires Owner approval on every
# opening balance with no amount threshold — every tenant gets a fixed
# doc_type=opening_balance rule (min_amount=0, required_role=Owner),
# same pattern as 0005_seed_iban_change_rule. Not meant to be editable/
# deletable from "قواعد الاعتماد" — see ApprovalRuleViewSet.
from django.db import migrations


def seed_opening_balance_rule(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    Role = apps.get_model("access", "Role")
    ApprovalRule = apps.get_model("approvals", "ApprovalRule")

    for tenant in Tenant.objects.all().iterator():
        owner_role = Role.objects.filter(tenant=tenant, name="Owner", is_system=True).first()
        if owner_role is None:
            continue
        ApprovalRule.objects.get_or_create(
            tenant=tenant,
            doc_type="opening_balance",
            min_amount=0,
            defaults={"required_role": owner_role, "is_active": True},
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0006_alter_approvalrule_doc_type"),
    ]

    operations = [
        migrations.RunPython(seed_opening_balance_rule, noop),
    ]
