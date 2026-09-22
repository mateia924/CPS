# Sprint 4.3: "طبّق قالب service كأب للحسابات الموجودة دون حذف أي حساب
# (اربطها بالمفاتيح المطابقة؛ الباقي تحت 'حسابات أخرى')".
#
# Every pre-4.3 tenant's chart is the flat 7-account
# DEFAULT_CHART_OF_ACCOUNTS (accounting/services.py, before this
# sprint): 1000 Cash, 1100 Accounts Receivable, 2100 Tax Payable, 3000
# Owner's Equity, 4000 Sales Revenue, 5000 General Expenses, 9100
# Currency Rounding Differences (added by 0006 above). This migration
# tags the 5 that have an obvious system_key match so
# get_system_account/get_or_create_party_role_account work correctly
# for these tenants too — no account is deleted, moved, renamed or
# re-parented (rule 10: "لا حذف بيانات"; re-nesting every existing
# tenant's chart under a brand-new parallel tree was judged too risky
# for a migration touching accounts that may already have posted
# JournalLines — see the Decision Log). "3000 Owner's Equity" and
# "5000 General Expenses" have no clean system_key match and are left
# untagged — effectively "حسابات أخرى" by not being system-key-tagged,
# without needing a literal wrapper account for it.
from django.db import migrations

CODE_TO_SYSTEM_KEY = {
    "1000": "CASH",
    "1100": "CUSTOMERS",
    "2100": "VAT_OUTPUT",
    "4000": "SALES",
    "9100": "ROUNDING",
}


def tag_existing_accounts(apps, schema_editor):
    Account = apps.get_model("accounting", "Account")
    for code, system_key in CODE_TO_SYSTEM_KEY.items():
        Account.objects.filter(code=code, system_key="").update(system_key=system_key)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0007_chart_of_accounts_hierarchy_fields"),
    ]

    operations = [
        migrations.RunPython(tag_existing_accounts, noop),
    ]
