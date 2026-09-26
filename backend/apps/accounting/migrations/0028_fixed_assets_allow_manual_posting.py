# Sprint 6.5.6 (decision C, first human UAT): 0027 backfilled FIXED_ASSETS
# with allow_manual_posting=False, same as the three depreciation/disposal
# control accounts. That was wrong — no depreciation/disposal code path
# ever posts to FIXED_ASSETS itself; only the asset's own purchase or an
# addition does, via an ordinary voucher/manual JV (decision 1). This
# flips the flag forward for every tenant's existing FIXED_ASSETS account
# instead of editing 0027 in place (migrations are point-in-time
# snapshots — see 0027's own note on never importing live app code).
from django.db import migrations


def allow_manual_posting_on_fixed_assets(apps, schema_editor):
    Account = apps.get_model("accounting", "Account")
    Account.objects.filter(system_key="FIXED_ASSETS", allow_manual_posting=False).update(
        allow_manual_posting=True
    )


def revert_to_control_account(apps, schema_editor):
    Account = apps.get_model("accounting", "Account")
    Account.objects.filter(system_key="FIXED_ASSETS", allow_manual_posting=True).update(
        allow_manual_posting=False
    )


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0027_backfill_fixed_asset_accounts"),
    ]

    operations = [
        migrations.RunPython(allow_manual_posting_on_fixed_assets, revert_to_control_account),
    ]
