# Sprint 6.5.18 (UAT item 9): migration 0006 backfilled account "9100"
# for every tenant that already existed before sprint 4.3's chart
# templates moved this same concept to code "5900" with its own
# proper Arabic name ("فروق تقريب العملة", system_key=ROUNDING) — 0006
# itself never translated its own hardcoded English name
# ("Currency Rounding Differences"), so every pre-4.3 tenant (the live
# evidence: tenant "fatma") has carried that English name on its own
# "9100" ever since. Pure chart-of-accounts metadata (a label), never a
# document or a balance — same category of fix as 0030/0032.
from django.db import migrations

_OLD_NAME = "Currency Rounding Differences"
_NEW_NAME = "فروق تقريب العملة"


def rename_to_arabic(apps, schema_editor):
    Account = apps.get_model("accounting", "Account")

    report = []
    accounts = Account.objects.filter(code="9100", name=_OLD_NAME)
    for account in accounts:
        account.name = _NEW_NAME
        account.save(update_fields=["name"])
        report.append({"tenant": account.tenant.subdomain, "code": account.code})

    print(f"[sprint 6.5.18 item 9] renamed account 9100 to Arabic: {report}")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0032_backfill_blank_account_type_and_normal_balance"),
    ]

    operations = [
        migrations.RunPython(rename_to_arabic, noop),
    ]
