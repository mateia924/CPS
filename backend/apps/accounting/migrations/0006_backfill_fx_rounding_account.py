# Sprint 4.2: apps.accounting.services.DEFAULT_CHART_OF_ACCOUNTS gained
# "9100 Currency Rounding Differences" (FX_ROUNDING_ACCOUNT_CODE) — new
# tenants get it automatically via seed_chart_of_accounts, but every
# existing tenant needs it added explicitly, same additive-only pattern
# as every prior sprint's backfill migration (no existing account is
# touched or removed).
from django.db import migrations


def backfill_fx_rounding_account(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    Account = apps.get_model("accounting", "Account")
    for tenant in Tenant.objects.all().iterator():
        Account.objects.get_or_create(
            tenant=tenant,
            code="9100",
            defaults={"name": "Currency Rounding Differences", "type": "expense", "is_system": True},
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0005_journal_currency_fields"),
    ]

    operations = [
        migrations.RunPython(backfill_fx_rounding_account, noop),
    ]
