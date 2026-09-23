# Sprint 5.5 (block 5.5.3, v2 decision 8): every chart-of-accounts
# template gets "فروق جرد الصندوق" (system_key=CASH_COUNT_VARIANCE)
# under 5000 — new tenants get it automatically via the corrected
# templates; every existing tenant (any business_type — cash counting
# isn't sector-specific like FX_REALIZED was) needs it added explicitly,
# same additive-only pattern as 0016.
from django.db import migrations


def backfill_cash_count_variance_account(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    Account = apps.get_model("accounting", "Account")
    for tenant in Tenant.objects.all().iterator():
        if Account.objects.filter(tenant=tenant, system_key="CASH_COUNT_VARIANCE").exists():
            continue
        parent = Account.objects.filter(tenant=tenant, code="5000").first()
        if parent is None:
            continue
        code = "5930" if not Account.objects.filter(tenant=tenant, code="5930").exists() else "5931"
        Account.objects.get_or_create(
            tenant=tenant,
            code=code,
            defaults={
                "name": "فروق جرد الصندوق",
                "type": "expense",
                "system_key": "CASH_COUNT_VARIANCE",
                "parent": parent,
                "is_system": True,
                "allow_manual_posting": False,
            },
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0021_remove_bogus_bank_statement_line_unique"),
    ]

    operations = [
        migrations.RunPython(backfill_cash_count_variance_account, noop),
    ]
