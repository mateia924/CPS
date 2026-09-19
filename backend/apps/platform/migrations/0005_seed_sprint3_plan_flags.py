from django.db import migrations

# docs/SYSTEM_ANALYSIS.md 3.3 (sprint 3): "تُخفى حسب TenantFeatures ...
# Free لا يراها، Business+ يراها" — Business and Enterprise both get
# treasury+assets; Free's AddField default (False) already covers it,
# no action needed there.


def set_flags(apps, schema_editor):
    Plan = apps.get_model("platform", "Plan")
    Plan.objects.filter(code__in=["business", "enterprise"]).update(
        feature_treasury=True, feature_assets=True
    )


def unset_flags(apps, schema_editor):
    Plan = apps.get_model("platform", "Plan")
    Plan.objects.filter(code__in=["business", "enterprise"]).update(
        feature_treasury=False, feature_assets=False
    )


class Migration(migrations.Migration):
    dependencies = [
        ("platform", "0004_plan_feature_assets_plan_feature_treasury"),
    ]

    operations = [
        migrations.RunPython(set_flags, unset_flags),
    ]
