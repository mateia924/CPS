# Sprint 6.5.17 (UAT item 1, continuation of 6.5.15 item 2): migration
# 0030 only backfilled six specific system_keys' Account rows. Any
# other account — in particular an auto-generated sub-account (Bank/
# CashBox/Custody's own gl_account, a party's sub-ledger account) —
# could in principle carry a blank type/normal_balance too, from
# before get_or_create_treasury_account/get_or_create_party_role_account
# started passing type=parent.type explicitly, or from any other
# historical write path. This backfills EVERY account tenant-wide with
# a blank type or normal_balance, deriving both from the account's own
# top-level tree root (never a document, never a balance — pure chart-
# of-accounts metadata, same category of fix as 0030).
from django.db import migrations

_DEFAULT_NORMAL_BALANCE_BY_TYPE = {
    "asset": "debit",
    "expense": "debit",
    "liability": "credit",
    "equity": "credit",
    "revenue": "credit",
}


def backfill_blank_account_type_and_normal_balance(apps, schema_editor):
    Account = apps.get_model("accounting", "Account")

    report = []
    blank_type_accounts = Account.objects.filter(type="")
    for account in blank_type_accounts:
        node = account
        seen = {account.id}
        while node.parent_id and node.parent_id not in seen and not node.type:
            node = node.parent
            seen.add(node.id)
        if node.type:
            account.type = node.type
            account.save(update_fields=["type"])
            report.append(
                {"tenant": account.tenant.subdomain, "code": account.code, "field": "type", "value": node.type}
            )

    blank_normal_balance_accounts = Account.objects.filter(normal_balance="")
    for account in blank_normal_balance_accounts:
        normal_balance = _DEFAULT_NORMAL_BALANCE_BY_TYPE.get(account.type)
        if normal_balance:
            account.normal_balance = normal_balance
            account.save(update_fields=["normal_balance"])
            report.append(
                {"tenant": account.tenant.subdomain, "code": account.code, "field": "normal_balance", "value": normal_balance}
            )

    print(f"[sprint 6.5.17 item 1] backfilled blank Account.type/normal_balance from tree root: {report}")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0031_fix_drifted_auto_fiscal_years"),
    ]

    operations = [
        migrations.RunPython(backfill_blank_account_type_and_normal_balance, noop),
    ]
