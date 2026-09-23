# Sprint 5.5 (block 5.5.0, CFO_REVIEW_1 C10): 3.15.9 requires approval
# on every IBAN change with no amount threshold — every tenant gets a
# fixed doc_type=iban_change rule (min_amount=0, required_role=Owner).
# Unlike the journal_entry default rule (0002), this one is not meant
# to be editable/deletable from the "قواعد الاعتماد" screen — see
# ApprovalRuleViewSet.
from django.db import migrations


def seed_iban_change_rule(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    Role = apps.get_model("access", "Role")
    ApprovalRule = apps.get_model("approvals", "ApprovalRule")

    for tenant in Tenant.objects.all().iterator():
        owner_role = Role.objects.filter(tenant=tenant, name="Owner", is_system=True).first()
        if owner_role is None:
            continue
        ApprovalRule.objects.get_or_create(
            tenant=tenant,
            doc_type="iban_change",
            min_amount=0,
            defaults={"required_role": owner_role, "is_active": True},
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0004_iban_change_request"),
    ]

    operations = [
        migrations.RunPython(seed_iban_change_rule, noop),
    ]
