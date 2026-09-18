from django.db import migrations

# docs/SYSTEM_ANALYSIS.md 3.14 sprint 2 spec: seed the three initial
# plans. Free = invoicing only, 2 users; Business = + inventory + cost
# centers; Enterprise = everything, no limits. No numeric limits are
# given for Business in the spec, so its max_* fields stay null
# (unlimited) — only Free's max_users=2 is explicit.
PLANS = [
    {
        "code": "free",
        "name": "Free",
        "max_users": 2,
        "max_branches": None,
        "max_invoices_per_month": None,
        "storage_mb": None,
        "feature_organization": False,
        "feature_cost_centers": False,
        "feature_inventory": False,
        "feature_purchasing": False,
        "feature_hr": False,
    },
    {
        "code": "business",
        "name": "Business",
        "max_users": None,
        "max_branches": None,
        "max_invoices_per_month": None,
        "storage_mb": None,
        "feature_organization": False,
        "feature_cost_centers": True,
        "feature_inventory": True,
        "feature_purchasing": False,
        "feature_hr": False,
    },
    {
        "code": "enterprise",
        "name": "Enterprise",
        "max_users": None,
        "max_branches": None,
        "max_invoices_per_month": None,
        "storage_mb": None,
        "feature_organization": True,
        "feature_cost_centers": True,
        "feature_inventory": True,
        "feature_purchasing": True,
        "feature_hr": True,
    },
]


def seed_plans(apps, schema_editor):
    Plan = apps.get_model("platform", "Plan")
    for data in PLANS:
        Plan.objects.get_or_create(code=data["code"], defaults=data)


def remove_seeded_plans(apps, schema_editor):
    Plan = apps.get_model("platform", "Plan")
    Plan.objects.filter(code__in=[p["code"] for p in PLANS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("platform", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_plans, remove_seeded_plans),
    ]
