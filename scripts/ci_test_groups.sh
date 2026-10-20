# shellcheck shell=bash
# CI coverage (2026-10-20): the ONE definition of how the backend suite is
# split into CI steps — read by .github/workflows/ci.yml and by
# scripts/check_ci_collection.sh. Until today ci.yml listed every file by
# name in four groups, frozen since 2ca1422 (2026-10-04); 24 test files
# added after that (all of sprint 7, 8.0, 8.1 and the pre-deploy guards)
# were never collected, and the gate passed on that false signal
# (docs/reports/2026-10-20-ci-coverage.md).
#
# The three named groups exist to narrow WHERE a run died (CI #62/#63).
# The fourth is not a list: it is every test file under backend/tests
# minus the three groups, so a new file runs by default. Paths are
# relative to backend/tests.

CI_GROUP_ACCOUNTING="
  test_chart_of_accounts.py test_db_triggers.py test_financial_controls.py test_fiscal_periods.py
  test_journal_engine.py test_multi_currency.py test_opening_balances.py test_period_checklist.py
  test_reports.py test_master_data.py test_master_data_screens.py test_mandatory_cost_center.py
  test_entity_subtree_scoping.py test_open_period_structural.py test_invoicing_e2e.py
  test_invoice_edit_void.py test_invoice_void_guard.py test_document_numbering.py
  test_migrations.py
"
CI_GROUP_ASSETS_TREASURY="
  test_asset_additions.py test_asset_declining_balance.py test_asset_depreciation.py
  test_asset_disposal.py test_asset_transfer.py test_fixed_asset_accounts.py
  test_fixed_assets_report.py test_fix_disposal_correction.py test_bank_reconciliation.py
  test_bank_statement_import.py test_reconciliation_dashboard_and_dashboard_cards.py
  test_reconciliation_report_and_cash_count.py test_treasury_entity_migration.py test_vouchers.py
  test_vouchers_transfers.py test_recurring_entries.py test_credit_limit.py test_iban_change.py
"
CI_GROUP_ATTACHMENTS_PERMISSIONS="
  test_attachments.py test_attachment_rules.py test_rbac.py test_dashboard_rbac.py
  test_platform_rbac.py test_platform_rbac_structural.py test_entity_scoped_viewsets.py
  test_entity_scoped_super_call.py test_entity_scope_structural.py test_entity_list_filters.py
  test_approvals.py test_approval_digest.py test_emergency_approval.py test_owner_protection.py
  test_guards.py test_settings_guards.py test_rate_limiting.py test_2fa.py
  test_must_change_password.py test_session_hygiene.py test_soft_delete.py
  test_soft_delete_structural.py
"

# pytest arguments for the fourth group: the whole directory, minus the
# files the three named groups already run.
ci_group_rest_args() {
  local f
  for f in $CI_GROUP_ACCOUNTING $CI_GROUP_ASSETS_TREASURY $CI_GROUP_ATTACHMENTS_PERMISSIONS; do
    printf -- "--ignore=%s " "$f"
  done
  printf "."
}

# Skips are tests that do not run, same family as uncollected files. Each
# CI step fails the Gate if its skip count rises above its ceiling here.
# Recorded 2026-10-20: 0 in every step (a CI-like run with the repo, git and
# gpg present skips nothing; the 59 skips seen in the dev container are all
# "no scripts/, no git, no gpg there"). Every skip and its reason:
# docs/reports/2026-10-20-ci-coverage.md. A new skip needs a deliberate bump
# here AND a dated line in that report, like any accepted exception.
CI_MAX_SKIPPED_ACCOUNTING=0
CI_MAX_SKIPPED_ASSETS_TREASURY=0
CI_MAX_SKIPPED_ATTACHMENTS_PERMISSIONS=0
CI_MAX_SKIPPED_REST=0
