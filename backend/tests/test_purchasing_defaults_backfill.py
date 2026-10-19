"""Sprint 8.0 (owner decision 2026-10-19): seed_purchasing_defaults brings
a tenant registered before 8.0 to exactly what registration gives one
registered after — the purchasing permissions on every system role, the
Purchasing role, and the five purchasing approval rules.

"Before 8.0" is built from a real registration with 8.0's additions taken
away again, and the test first checks that the stripped tenant really
differs (a setup step that removes nothing would make the comparison pass
by default). Identity is compared on the whole role/permission and
approval-rule picture of both tenants, not on the purchasing part only.
"""

from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from rest_framework.test import APIClient

from apps.access.models import Role
from apps.approvals.models import ApprovalRule
from apps.purchasing.services import PURCHASING_DOC_TYPES, purchasing_permission_codes
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


def _strip_8_0(tenant):
    """What a tenant registered before 8.0 looks like: no purchasing rules,
    no purchasing permission on any role, no Purchasing role."""
    ApprovalRule.objects.filter(tenant=tenant, doc_type__in=PURCHASING_DOC_TYPES).delete()
    for role in Role.objects.filter(tenant=tenant):
        role.permissions.remove(*role.permissions.filter(code__startswith="purchasing."))
    Role.objects.filter(tenant=tenant, name="Purchasing").delete()


def _picture(tenant):
    roles = {
        role.name: (role.is_system, tuple(sorted(role.permissions.values_list("code", flat=True))))
        for role in Role.objects.filter(tenant=tenant, deleted_at__isnull=True)
    }
    rules = sorted(
        (rule.doc_type, str(rule.min_amount), rule.required_role.name, rule.is_active)
        for rule in ApprovalRule.objects.filter(tenant=tenant, deleted_at__isnull=True).select_related("required_role")
    )
    return roles, rules


def _seed(*args):
    out = StringIO()
    call_command("seed_purchasing_defaults", *args, stdout=out)
    return out.getvalue()


@pytest.fixture
def two_tenants(db):
    PlanFactory(code="free")
    after = _register("after-8-0")
    before = _register("before-8-0")
    _strip_8_0(before)
    return before, after


@pytest.mark.django_db
def test_a_pre_8_0_tenant_ends_up_identical_to_one_registered_after(two_tenants):
    before, after = two_tenants
    assert _picture(before) != _picture(after), "the stripped tenant must really lack 8.0's additions"
    assert not Role.objects.filter(tenant=before, name="Purchasing").exists()
    assert not ApprovalRule.objects.filter(tenant=before, doc_type="supplier_bill").exists()

    output = _seed("--tenant", "before-8-0")

    assert _picture(before) == _picture(after)
    assert "role created: Purchasing" in output
    assert "approval rules created (min=0 -> Owner): " + ", ".join(sorted(PURCHASING_DOC_TYPES)) in output
    owner_line = "Owner: + " + ", ".join(purchasing_permission_codes())
    assert owner_line in output


@pytest.mark.django_db
def test_a_second_run_changes_nothing(two_tenants):
    before, _after = two_tenants
    _seed("--tenant", "before-8-0")
    picture = _picture(before)
    role_ids = set(Role.objects.filter(tenant=before).values_list("id", flat=True))
    rule_ids = set(ApprovalRule.objects.filter(tenant=before).values_list("id", flat=True))

    output = _seed("--tenant", "before-8-0")

    assert _picture(before) == picture
    assert set(Role.objects.filter(tenant=before).values_list("id", flat=True)) == role_ids
    assert set(ApprovalRule.objects.filter(tenant=before).values_list("id", flat=True)) == rule_ids
    assert "before-8-0: no change" in output and "0 tenant(s) changed." in output


@pytest.mark.django_db
def test_dry_run_writes_nothing_and_names_what_it_would_add(two_tenants):
    before, _after = two_tenants
    picture = _picture(before)

    output = _seed("--tenant", "before-8-0", "--dry-run")

    assert _picture(before) == picture
    assert "DRY RUN" in output and "role created: Purchasing" in output and "1 tenant(s) would change." in output


@pytest.mark.django_db
def test_a_named_tenant_run_leaves_every_other_tenant_alone(two_tenants):
    before, after = two_tenants
    other = _register("other-8-0")
    _strip_8_0(other)
    other_picture = _picture(other)

    _seed("--tenant", "before-8-0")

    assert _picture(other) == other_picture
    assert _picture(before) == _picture(after)


@pytest.mark.django_db
def test_all_tenants_skips_archived_ones(two_tenants):
    before, after = two_tenants
    archived = _register("archived-8-0")
    _strip_8_0(archived)
    Tenant.objects.filter(pk=archived.pk).update(status=Tenant.Status.ARCHIVED)
    archived_picture = _picture(archived)

    output = _seed("--all-tenants")

    assert _picture(before) == _picture(after)
    assert _picture(archived) == archived_picture
    assert "Excluding 1 archived tenant(s): archived-8-0" in output


@pytest.mark.django_db
def test_the_target_must_be_named(two_tenants):
    with pytest.raises(CommandError, match="Name the target"):
        _seed()
    Tenant.objects.filter(subdomain="before-8-0").update(status=Tenant.Status.ARCHIVED)
    with pytest.raises(CommandError, match="archived"):
        _seed("--tenant", "before-8-0")


@pytest.mark.django_db
def test_a_tenant_without_an_owner_role_is_not_reported_as_done(two_tenants):
    """seed_default_approval_rules silently skips a rule whose role is
    missing. The command must not: with no Owner role, the supplier_bill
    rule cannot exist, and that is exactly the automatic-approval state."""
    before, _after = two_tenants
    owner = Role.objects.get(tenant=before, name="Owner")
    ApprovalRule.objects.filter(tenant=before).delete()
    owner.delete()

    with pytest.raises(CommandError, match="Not complete"):
        _seed("--tenant", "before-8-0")
    assert not ApprovalRule.objects.filter(tenant=before, doc_type="supplier_bill").exists()
