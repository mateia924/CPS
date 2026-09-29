# Sprint 6.5.15 (UAT item 2): the real cause of "1750 (مجمع الإهلاك)
# يظهر +1,000 تحت الأصول" — four earlier data migrations (0006, 0016,
# 0022, 0027) backfill system accounts for existing tenants via
# apps.get_model()'s historical Account model, which has no custom
# save() override, so Account.normal_balance was never defaulted from
# type the way the live model's save() does for every account created
# through the real seed_chart_of_accounts() path. Those rows are left
# with normal_balance="" — apps.reports.services.account_balances()'s
# sign = 1 if normal_balance == DEBIT else -1 then silently falls into
# the CREDIT branch for a real DEBIT-normal asset/expense account,
# flipping its sign in every report that reads it. Purely a chart-of-
# accounts configuration fix — no JournalLine, no document, no balance
# is touched; only this one blank field on whichever Account rows have
# it, tenant-wide (every affected tenant, not just one).
from django.db import migrations

_DEFAULT_NORMAL_BALANCE_BY_TYPE = {
    "asset": "debit",
    "expense": "debit",
    "liability": "credit",
    "equity": "credit",
    "revenue": "credit",
}


def backfill_blank_normal_balance(apps, schema_editor):
    Account = apps.get_model("accounting", "Account")

    report = []
    for acc_type, normal_balance in _DEFAULT_NORMAL_BALANCE_BY_TYPE.items():
        accounts = Account.objects.filter(type=acc_type, normal_balance="")
        codes = list(accounts.values_list("tenant__subdomain", "code"))
        updated = accounts.update(normal_balance=normal_balance)
        if updated:
            report.append({"type": acc_type, "normal_balance": normal_balance, "updated": updated, "accounts": codes})

    print(f"[sprint 6.5.15 item 2] backfilled blank Account.normal_balance: {report}")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0029_legacy_duplicate_number"),
    ]

    operations = [
        migrations.RunPython(backfill_blank_normal_balance, noop),
    ]
