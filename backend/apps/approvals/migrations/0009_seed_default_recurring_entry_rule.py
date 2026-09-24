# Sprint 6.4 (decision 9): "قاعدة افتراضية مزروعة min_amount=0 → Owner
# (قابلة للتعديل كقاعدة journal_entry في 4.5)" — same default-rule
# pattern as 0002_seed_default_jv_rule, freely editable/deletable
# afterward (unlike the fixed IBAN_CHANGE/OPENING_BALANCE rules).
from django.db import migrations


def seed_default_recurring_entry_rule(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    Role = apps.get_model("access", "Role")
    ApprovalRule = apps.get_model("approvals", "ApprovalRule")

    for tenant in Tenant.objects.all().iterator():
        owner_role = Role.objects.filter(tenant=tenant, name="Owner", is_system=True).first()
        if owner_role is None:
            continue
        ApprovalRule.objects.get_or_create(
            tenant=tenant,
            doc_type="recurring_entry",
            min_amount=0,
            defaults={"required_role": owner_role, "is_active": True},
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0008_alter_approvalrule_doc_type"),
    ]

    operations = [
        migrations.RunPython(seed_default_recurring_entry_rule, noop),
    ]
