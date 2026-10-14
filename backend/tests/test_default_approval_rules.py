"""7.4 follow-up: a tenant registered over the API is born with the COMPLETE
default ApprovalRule set — not only the two registration used to hard-code
(journal_entry, iban_change) while every later default lived only in a
backfill migration (docs/SYSTEM_ANALYSIS.md §11).

The expected set is written out here on purpose, not read from
apps.approvals.defaults: removing a doc_type from the definition must fail
this test by name, not silently shrink what it checks.
"""

import pytest

from apps.approvals.models import ApprovalRule
from apps.tenants.models import Tenant

EXPECTED_DEFAULT_DOC_TYPES = {
    "journal_entry",
    "iban_change",
    "opening_balance",
    "recurring_entry",
    "asset_depreciation",
    "asset_addition",
    "asset_disposal",
    "stock_receipt",
    "stock_issue",
    "stock_transfer",
    "stock_count",
}


@pytest.mark.django_db
def test_a_tenant_registered_over_the_api_has_every_default_approval_rule(client):
    response = client.post(
        "/api/auth/register/",
        {
            "company_name": "Defaults Co", "subdomain": "approval-defaults",
            "email": "owner@approval-defaults.test", "password": "TestPass!2026",
        },
        content_type="application/json",
    )
    assert response.status_code == 201, response.data
    tenant = Tenant.objects.get(subdomain="approval-defaults")

    rules = ApprovalRule.objects.filter(tenant=tenant, is_active=True, deleted_at__isnull=True)
    present = set(rules.values_list("doc_type", flat=True))
    missing = EXPECTED_DEFAULT_DOC_TYPES - present
    assert not missing, f"registered tenant is missing default approval rules for: {sorted(missing)}"
    assert present == EXPECTED_DEFAULT_DOC_TYPES, f"unexpected extra rules: {sorted(present - EXPECTED_DEFAULT_DOC_TYPES)}"
    for rule in rules.select_related("required_role"):
        assert (rule.min_amount, rule.required_role.name, rule.required_role.is_system) == (0, "Owner", True), rule.doc_type
    assert rules.count() == len(EXPECTED_DEFAULT_DOC_TYPES)  # exactly one each, no duplicates


def test_a_backfill_migration_asking_for_a_doc_type_the_definition_lacks_fails_before_any_tenant():
    """Checked before the tenant loop: a fresh migrate (no tenants) must
    still refuse, or the guard only fires on databases that have data."""
    from apps.approvals.defaults import backfill_default_approval_rules

    with pytest.raises(KeyError, match="no_such_doc_type"):
        backfill_default_approval_rules(None, ["no_such_doc_type"])
