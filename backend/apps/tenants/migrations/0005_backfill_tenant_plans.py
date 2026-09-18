from django.db import migrations

# docs/SYSTEM_ANALYSIS.md 3.14 sprint 2 spec: "المستأجرون الحاليون
# يُربطون بـ Enterprise تلقائيًا" — every tenant that predates plans
# gets the Enterprise plan and is marked ACTIVE (not TRIAL — these are
# real, already-onboarded tenants, not new signups).


def backfill_tenant_plans(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    Plan = apps.get_model("platform", "Plan")
    enterprise = Plan.objects.get(code="enterprise")
    Tenant.objects.filter(plan__isnull=True).update(plan=enterprise, status="active")


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0004_tenant_plan_tenant_status_tenant_trial_ends_at"),
        ("platform", "0002_seed_plans"),
    ]

    operations = [
        migrations.RunPython(backfill_tenant_plans, noop_reverse),
    ]
