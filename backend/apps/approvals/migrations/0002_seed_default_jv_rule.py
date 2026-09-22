# Sprint 4.5: 3.15.9's rule "لا قيد يدوي يُرحَّل بلا اعتماد" was a
# hardcoded check in sprint 4.4 (accounting.services). Generalizing to
# the real ApprovalRule engine means that baseline must now be an
# actual seeded rule, or every tenant would silently lose it (no rule
# configured = auto-approve). Every existing tenant gets a default
# journal_entry rule at min_amount=0 (applies to every manual JV
# regardless of amount), required_role=Owner — same default the
# hardcoded 4.4 version enforced. Tenants remain free to edit/remove it
# via the settings screen afterward.
from django.db import migrations


def seed_default_jv_rule(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    Role = apps.get_model("access", "Role")
    ApprovalRule = apps.get_model("approvals", "ApprovalRule")

    for tenant in Tenant.objects.all().iterator():
        owner_role = Role.objects.filter(tenant=tenant, name="Owner", is_system=True).first()
        if owner_role is None:
            continue
        ApprovalRule.objects.get_or_create(
            tenant=tenant,
            doc_type="journal_entry",
            min_amount=0,
            defaults={"required_role": owner_role, "is_active": True},
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_default_jv_rule, noop),
    ]
