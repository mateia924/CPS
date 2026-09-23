# Sprint 5.7 (CFO_REVIEW_1 C2): every existing tenant's chart gets
# `allow_manual_posting=False` flipped on its control accounts — a
# pure reclassification (no amount, no journal line, no account is
# moved or created), same additive-only spirit as 0006/0016's backfill
# migrations. New tenants get this automatically going forward via
# get_or_create_party_role_account/get_or_create_treasury_account and
# the chart-template loader (both updated alongside this migration).
from django.db import migrations

CONTROL_SYSTEM_KEYS = {
    "VAT_OUTPUT", "VAT_INPUT", "VAT_NON_DEDUCTIBLE", "FX_REALIZED", "FX_UNREALIZED",
    "ROUNDING", "OPENING_BALANCE", "RETAINED_EARNINGS",
}


def backfill_control_accounts(apps, schema_editor):
    Account = apps.get_model("accounting", "Account")
    Bank = apps.get_model("treasury", "Bank")
    CashBox = apps.get_model("treasury", "CashBox")
    Custody = apps.get_model("treasury", "Custody")

    Account.objects.filter(party__isnull=False).update(allow_manual_posting=False)
    Account.objects.filter(system_key__in=CONTROL_SYSTEM_KEYS).update(allow_manual_posting=False)

    treasury_account_ids = set()
    for model in (Bank, CashBox, Custody):
        treasury_account_ids.update(
            model.objects.filter(gl_account__isnull=False).values_list("gl_account_id", flat=True)
        )
    if treasury_account_ids:
        Account.objects.filter(id__in=treasury_account_ids).update(allow_manual_posting=False)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0017_account_allow_manual_posting_and_more"),
        ("treasury", "0004_cashbox_max_balance_custody_limit_amount"),
    ]

    operations = [
        migrations.RunPython(backfill_control_accounts, noop),
    ]
