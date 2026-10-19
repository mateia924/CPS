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
    # Sprint 8.0 (D3): registration only, no backfill onto existing tenants.
    "purchase_order",
    "supplier_bill",
    "purchase_return",
    "landed_cost",
    "party_netting",
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


# ------------------------------------------- one-tenant backfill command

FIVE = ["opening_balance", "recurring_entry", "asset_addition", "asset_depreciation", "asset_disposal"]


def _active(tenant):
    return set(
        ApprovalRule.objects.filter(tenant=tenant, is_active=True, deleted_at__isnull=True).values_list("doc_type", flat=True)
    )


def _backfill(subdomain, doc_types):
    from io import StringIO

    from django.core.management import call_command

    out = StringIO()
    args = ["backfill_default_approval_rules", "--subdomain", subdomain]
    for d in doc_types:
        args += ["--doc-type", d]
    call_command(*args, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_backfill_adds_only_the_named_doc_types_to_only_the_named_tenant_and_a_second_run_changes_nothing(
    user_a, user_b,
):
    from apps.access.models import Role
    from apps.approvals.defaults import seed_default_approval_rules

    tenant_a, tenant_b = user_a.tenant, user_b.tenant
    # tenant_a: the 1cps shape — everything except the five.
    others = [d for d in EXPECTED_DEFAULT_DOC_TYPES if d not in FIVE]
    seed_default_approval_rules(tenant_a, ApprovalRule=ApprovalRule, Role=Role, doc_types=others)
    before_b = _active(tenant_b)
    assert _active(tenant_a) == set(others)

    first = _backfill("tenant-a", FIVE)

    assert _active(tenant_a) == EXPECTED_DEFAULT_DOC_TYPES
    assert _active(tenant_b) == before_b  # the other tenant is untouched
    # 6 -> 11 when written (7.4); 8.0's five purchasing defaults raised both by 5.
    assert f"BEFORE — tenant-a: {len(others)} active rule(s)" in first
    assert f"AFTER — tenant-a: {len(EXPECTED_DEFAULT_DOC_TYPES)} active rule(s)" in first
    assert f"added 5: {', '.join(sorted(FIVE))}" in first

    count = ApprovalRule.objects.filter(tenant=tenant_a).count()
    second = _backfill("tenant-a", FIVE)

    assert ApprovalRule.objects.filter(tenant=tenant_a).count() == count
    assert "added 0: (none — already present)" in second


@pytest.mark.django_db
def test_backfill_refuses_an_archived_tenant_and_an_unknown_doc_type(user_a):
    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match="Not a default doc_type"):
        _backfill("tenant-a", ["invoice"])
    Tenant.objects.filter(pk=user_a.tenant.pk).update(status=Tenant.Status.ARCHIVED)
    with pytest.raises(CommandError, match="archived"):
        _backfill("tenant-a", FIVE)
    assert _active(user_a.tenant) == set()
