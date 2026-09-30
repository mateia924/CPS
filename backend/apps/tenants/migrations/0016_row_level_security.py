# Sprint 6.6.3 (item 1): Postgres Row-Level Security as a third layer
# on top of TenantScopedViewSet/EntityScopedMixin — see apps.tenants.
# services.configure_database_roles_and_rls's own docstring for the
# full design (the restricted `cps_app` role, the per-table policy,
# why NULL/missing `cps.tenant_id` resolves to zero rows rather than
# erroring). Explicitly depends on the LATEST migration of every app
# that could plausibly have a tenant-scoped model, so this always runs
# strictly after every table it will touch actually exists — it reads
# the CURRENT model registry (apps.common.rls.tenant_scoped_tables),
# not this migration's own historical app-state snapshot, precisely so
# a table created by a FUTURE migration is covered automatically
# without this file ever needing to change; that same property is
# exactly why the ordering guarantee matters here at creation time.
#
# Not reversible: dropping the tenant_isolation policies / disabling
# RLS / dropping cps_app on a `migrate` backwards would silently
# reopen the exact isolation gap this migration exists to close, on
# whatever database it's run against — including, one day, a live
# one. If a future sprint genuinely needs to undo this, that should be
# its own deliberate, reviewed migration, not an automatic `migrate
# tenants 0015`.

from django.db import migrations

from apps.tenants.services import configure_database_roles_and_rls


def forwards(apps, schema_editor):
    configure_database_roles_and_rls(schema_editor.connection)


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0015_tenant_require_2fa_for_roles"),
        ("accounts", "0004_user_must_change_password_user_totp_confirmed_and_more"),
        ("accounting", "0034_journalentry_accounting_je_entity_date_idx_and_more"),
        ("access", "0019_seed_asset_depreciation_permissions"),
        ("approvals", "0015_seed_default_asset_disposal_rule"),
        ("assets", "0008_assettransfer_reason"),
        ("attachments", "0003_attachmentrule"),
        ("numbering", "0004_merge_simplified_mode_sequences"),
        ("organization", "0005_legalentity_opening_approved_at"),
        ("parties", "0005_backfill_credit_limit_from_role_details"),
        ("platform", "0006_plan_max_file_mb"),
        ("sales", "0023_invoice_sales_invoice_entity_date_idx_and_more"),
        ("treasury", "0008_move_untouched_treasury_to_branch"),
        ("vouchers", "0005_voucher_vouchers_entity_date_idx_and_more"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
