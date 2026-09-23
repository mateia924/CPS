# Sprint 5.3: apps/accounting/chart_templates/service.json was missing
# "5910 فروق عملة محققة" (system_key=FX_REALIZED) — trading/
# manufacturing/holding already had it, service (the tenant default)
# didn't, so a service-type tenant's voucher engine would have nowhere
# to post a realized FX gain/loss. New tenants get it automatically via
# the corrected template; every existing service-type tenant needs it
# added explicitly, same additive-only pattern as 0006 (no existing
# account is touched or removed).
from django.db import migrations


def backfill_fx_realized_account(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    Account = apps.get_model("accounting", "Account")
    for tenant in Tenant.objects.filter(business_type="service").iterator():
        if Account.objects.filter(tenant=tenant, system_key="FX_REALIZED").exists():
            continue
        parent = Account.objects.filter(tenant=tenant, code="5000").first()
        if parent is None:
            continue
        Account.objects.get_or_create(
            tenant=tenant,
            code="5910",
            defaults={
                "name": "فروق عملة محققة",
                "type": "expense",
                "system_key": "FX_REALIZED",
                "parent": parent,
                "allow_posting": True,
                "is_system": True,
            },
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0015_backfill_journal_line_currency_and_rate"),
    ]

    operations = [
        migrations.RunPython(backfill_fx_realized_account, noop),
    ]
