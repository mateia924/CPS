"""seed_purchasing_defaults — ADDITIVE ONLY (owner decision 2026-10-20).

On a tenant that predates purchasing it creates what is missing: the four
purchasing system accounts, the withholding codes of its country (as
examples), the purchasing.* permission rows, the Purchasing role (view/
manage, no users) and the five purchasing approval rules. It modifies NO
existing role: Owner and Accountant keep exactly the permission sets they
had (until 2026-10-20 the seed added purchasing.* to both).

"Before purchasing" is built from a real registration with those additions
taken away again, and each test first checks the stripped tenant really
lacks them (a setup step that removes nothing would make every assertion
pass by default).
"""

from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from rest_framework.test import APIClient

from apps.access.models import Permission, Role
from apps.accounting.models import Account
from apps.approvals.models import ApprovalRule
from apps.purchasing.models import WithholdingTaxCode
from apps.purchasing.services import PURCHASING_DOC_TYPES, PURCHASING_SYSTEM_KEYS, withholding_table
from apps.tenants.models import Tenant

from .factories import PlanFactory

_SECRET = "-".join(["Backfill", "Purch", "2026!"])


def _register(subdomain):
    response = APIClient().post(
        "/api/auth/register/",
        {"company_name": subdomain, "subdomain": subdomain, "email": f"owner@{subdomain}.test", "password": _SECRET},
        format="json",
    )
    assert response.status_code == 201, response.content
    return Tenant.objects.get(subdomain=subdomain)


def _strip_purchasing(tenant):
    """What a tenant registered before purchasing looks like."""
    ApprovalRule.objects.filter(tenant=tenant, doc_type__in=PURCHASING_DOC_TYPES).delete()
    for role in Role.objects.filter(tenant=tenant):
        role.permissions.remove(*role.permissions.filter(code__startswith="purchasing."))
    Role.objects.filter(tenant=tenant, name="Purchasing").delete()
    Account.objects.filter(tenant=tenant, system_key__in=PURCHASING_SYSTEM_KEYS).delete()
    WithholdingTaxCode.objects.filter(tenant=tenant).delete()


def _role_sets(tenant):
    return {
        role.name: frozenset(role.permissions.values_list("code", flat=True))
        for role in Role.objects.filter(tenant=tenant, deleted_at__isnull=True)
    }


def _seed(*args):
    out = StringIO()
    call_command("seed_purchasing_defaults", *args, stdout=out)
    return out.getvalue()


@pytest.fixture
def before(db):
    PlanFactory(code="free")
    tenant = _register("before-purch")
    _strip_purchasing(tenant)
    assert not Role.objects.filter(tenant=tenant, name="Purchasing").exists()
    assert not ApprovalRule.objects.filter(tenant=tenant, doc_type="supplier_bill").exists()
    assert not Account.objects.filter(tenant=tenant, system_key__in=PURCHASING_SYSTEM_KEYS).exists()
    assert not WithholdingTaxCode.objects.filter(tenant=tenant).exists()
    return tenant


@pytest.mark.django_db
def test_the_seed_creates_what_is_missing_and_changes_no_existing_role(before):
    roles_before = _role_sets(before)
    assert "Owner" in roles_before and "Accountant" in roles_before

    output = _seed("--tenant", "before-purch")

    roles_after = _role_sets(before)
    for name, codes in roles_before.items():
        assert roles_after[name] == codes, f"the seed changed the existing role {name}"
    assert not any(code.startswith("purchasing.") for code in roles_after["Owner"] | roles_after["Accountant"])
    purchasing = Role.objects.get(tenant=before, name="Purchasing")
    assert purchasing.is_system and not purchasing.users.exists()
    assert roles_after["Purchasing"] == {"purchasing.view", "purchasing.manage"}
    assert set(
        ApprovalRule.objects.filter(tenant=before, doc_type__in=PURCHASING_DOC_TYPES).values_list("doc_type", flat=True)
    ) == set(PURCHASING_DOC_TYPES)
    assert set(
        Account.objects.filter(tenant=before, system_key__in=PURCHASING_SYSTEM_KEYS).values_list("system_key", flat=True)
    ) == set(PURCHASING_SYSTEM_KEYS)
    assert WithholdingTaxCode.objects.filter(tenant=before, country="SA").count() == len(withholding_table("SA"))
    assert "role created: Purchasing (no users)" in output
    assert "existing roles: unchanged (additive only)" in output


@pytest.mark.django_db
def test_an_existing_purchasing_role_is_left_exactly_as_it_is(before):
    custom = Role.objects.create(tenant=before, name="Purchasing", is_system=True)
    custom.permissions.set(Permission.objects.filter(code="purchasing.view"))

    _seed("--tenant", "before-purch")

    assert set(custom.permissions.values_list("code", flat=True)) == {"purchasing.view"}


@pytest.mark.django_db
def test_missing_permission_rows_are_created_never_updated(before):
    Permission.objects.filter(code__startswith="purchasing.").delete()
    Permission.objects.filter(code="invoices.view").update(description="edited by an operator")

    output = _seed("--tenant", "before-purch")

    assert set(Permission.objects.filter(code__startswith="purchasing.").values_list("code", flat=True)) == {
        "purchasing.view", "purchasing.manage", "purchasing.post", "purchasing.override_match",
    }
    assert Permission.objects.get(code="invoices.view").description == "edited by an operator"
    assert "permission rows created:" in output


@pytest.mark.django_db
def test_a_second_run_changes_nothing(before):
    _seed("--tenant", "before-purch")
    roles = _role_sets(before)
    rule_ids = set(ApprovalRule.objects.filter(tenant=before).values_list("id", flat=True))
    account_ids = set(Account.objects.filter(tenant=before).values_list("id", flat=True))

    output = _seed("--tenant", "before-purch")

    assert _role_sets(before) == roles
    assert set(ApprovalRule.objects.filter(tenant=before).values_list("id", flat=True)) == rule_ids
    assert set(Account.objects.filter(tenant=before).values_list("id", flat=True)) == account_ids
    assert "before-purch: no change" in output and "0 tenant(s) changed." in output


@pytest.mark.django_db
def test_dry_run_writes_nothing_and_names_what_it_would_add(before):
    roles = _role_sets(before)

    output = _seed("--tenant", "before-purch", "--dry-run")

    assert _role_sets(before) == roles
    assert not Role.objects.filter(tenant=before, name="Purchasing").exists()
    assert not Account.objects.filter(tenant=before, system_key__in=PURCHASING_SYSTEM_KEYS).exists()
    assert "DRY RUN" in output and "role created: Purchasing" in output and "1 tenant(s) would change." in output


@pytest.mark.django_db
def test_a_named_tenant_run_leaves_every_other_tenant_alone(before):
    other = _register("other-purch")
    _strip_purchasing(other)
    other_roles = _role_sets(other)

    _seed("--tenant", "before-purch")

    assert _role_sets(other) == other_roles
    assert not Role.objects.filter(tenant=other, name="Purchasing").exists()


@pytest.mark.django_db
def test_all_tenants_skips_archived_ones(before):
    archived = _register("archived-purch")
    _strip_purchasing(archived)
    Tenant.objects.filter(pk=archived.pk).update(status=Tenant.Status.ARCHIVED)

    output = _seed("--all-tenants")

    assert Role.objects.filter(tenant=before, name="Purchasing").exists()
    assert not Role.objects.filter(tenant=archived, name="Purchasing").exists()
    assert "Excluding 1 archived tenant(s): archived-purch" in output


@pytest.mark.django_db
def test_the_target_must_be_named(before):
    with pytest.raises(CommandError, match="Name the target"):
        _seed()
    Tenant.objects.filter(subdomain="before-purch").update(status=Tenant.Status.ARCHIVED)
    with pytest.raises(CommandError, match="archived"):
        _seed("--tenant", "before-purch")


@pytest.mark.django_db
def test_a_tenant_without_an_owner_role_is_not_reported_as_done(before):
    """seed_default_approval_rules silently skips a rule whose role is
    missing. The command must not: with no Owner role, the supplier_bill
    rule cannot exist, and that is exactly the automatic-approval state."""
    owner = Role.objects.get(tenant=before, name="Owner")
    ApprovalRule.objects.filter(tenant=before).delete()
    owner.delete()

    with pytest.raises(CommandError, match="Not complete"):
        _seed("--tenant", "before-purch")
    assert not ApprovalRule.objects.filter(tenant=before, doc_type="supplier_bill").exists()
