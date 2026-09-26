# Sprint 6.5 (block 6.5.0, decision 2): four new system accounts for
# fixed-asset depreciation — new tenants get them from the corrected
# chart templates automatically; every existing tenant needs them added
# explicitly, same additive-only idempotent pattern as 0016/0022
# (migrations never import live app code — hence the constants below
# are a plain copy, not an import from apps.accounting.services).
from django.db import migrations

_NEW_ACCOUNTS = [
    {"code": "1700", "name": "الأصول الثابتة", "type": "asset", "system_key": "FIXED_ASSETS", "parent_code": "1000"},
    {
        "code": "1750", "name": "مجمع إهلاك الأصول الثابتة", "type": "asset",
        "system_key": "ACCUM_DEPRECIATION", "parent_code": "1000",
    },
    {
        "code": "5150", "name": "مصروف إهلاك الأصول الثابتة", "type": "expense",
        "system_key": "DEPRECIATION_EXPENSE", "parent_code": "5000",
    },
    {
        "code": "4900", "name": "أرباح/خسائر استبعاد الأصول", "type": "revenue",
        "system_key": "DISPOSAL_GAIN_LOSS", "parent_code": "4000",
    },
]


def backfill_fixed_asset_accounts(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    Account = apps.get_model("accounting", "Account")
    for tenant in Tenant.objects.all().iterator():
        for spec in _NEW_ACCOUNTS:
            if Account.objects.filter(tenant=tenant, system_key=spec["system_key"]).exists():
                continue
            parent = Account.objects.filter(tenant=tenant, code=spec["parent_code"]).first()
            if parent is None:
                continue
            code = spec["code"]
            if Account.objects.filter(tenant=tenant, code=code).exists():
                # Same collision-avoidance as 0022: a pre-existing
                # custom account already sits on this exact code —
                # never overwrite it, take the next free code instead.
                suffix = 1
                while Account.objects.filter(tenant=tenant, code=f"{code[:-1]}{suffix}").exists():
                    suffix += 1
                code = f"{code[:-1]}{suffix}"
            Account.objects.get_or_create(
                tenant=tenant,
                code=code,
                defaults={
                    "name": spec["name"],
                    "type": spec["type"],
                    "system_key": spec["system_key"],
                    "parent": parent,
                    "is_system": True,
                    "allow_manual_posting": False,
                },
            )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0026_recurringentry_recurringinstallment"),
    ]

    operations = [
        migrations.RunPython(backfill_fixed_asset_accounts, noop),
    ]
