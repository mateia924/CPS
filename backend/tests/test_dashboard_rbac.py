"""Sprint 6.9.1 (item A, decisions 1-3): RBAC on the aggregated
dashboard-summary card, correct per-user filtering on the pending-
approvals inbox (including the single-active-user exemption), and
HasModulePermission no longer 500ing on a plain APIView.
"""

from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.access.permissions import HasModulePermission
from apps.access.services import seed_default_roles
from apps.accounting.models import Account
from apps.accounting.services import create_manual_journal_entry, submit_journal_entry_for_approval
from apps.approvals.models import ApprovalRule
from apps.organization.models import LegalEntity

from .factories import UserFactory


def _roles(tenant):
    from apps.access.models import Role

    existing = {r.name: r for r in Role.objects.filter(tenant=tenant, is_system=True)}
    return existing or seed_default_roles(tenant)


def _branch(tenant):
    return LegalEntity.objects.get(tenant=tenant, entity_type=LegalEntity.Type.BRANCH)


@pytest.mark.django_db
def test_dashboard_summary_requires_accounting_view(tenant_a, user_a, client_a):
    roles = _roles(tenant_a)
    sales_user = UserFactory(tenant=tenant_a, email="sales@dashboard-rbac.test")
    sales_user.roles.add(roles["Sales"])
    sales_client = APIClient()
    sales_client.force_authenticate(user=sales_user)

    denied = sales_client.get("/api/dashboard/summary/")
    assert denied.status_code == 403

    allowed = client_a.get("/api/dashboard/summary/")
    assert allowed.status_code == 200, allowed.data


@pytest.mark.django_db
def test_pending_approvals_empty_for_user_without_approval_role(tenant_a, user_a, client_a):
    roles = _roles(tenant_a)
    ApprovalRule.objects.create(
        tenant=tenant_a, doc_type=ApprovalRule.DocType.JOURNAL_ENTRY, min_amount=0, required_role=roles["Owner"]
    )
    # A second Owner so tenant_a is no longer single-active-user — the
    # accountant below genuinely has no approval role at all, and must
    # see nothing, not the whole tenant's queue.
    UserFactory(tenant=tenant_a, email="other-owner@dashboard-rbac.test").roles.add(roles["Owner"])
    accountant = UserFactory(tenant=tenant_a, email="accountant@dashboard-rbac.test")
    accountant.roles.add(roles["Accountant"])
    accountant_client = APIClient()
    accountant_client.force_authenticate(user=accountant)

    cash = Account.objects.get(tenant=tenant_a, system_key="CASH")
    sales = Account.objects.get(tenant=tenant_a, system_key="SALES")
    entry = create_manual_journal_entry(
        tenant=tenant_a, user=user_a, legal_entity=_branch(tenant_a), date=date(2026, 1, 5),
        line_specs=[
            {"account": cash, "debit_fc": Decimal("50.00"), "credit_fc": Decimal("0")},
            {"account": sales, "debit_fc": Decimal("0"), "credit_fc": Decimal("50.00")},
        ],
        currency="SAR", exchange_rate=Decimal("1"),
    )
    submit_journal_entry_for_approval(entry, user_a)

    response = accountant_client.get("/api/approvals/pending/")
    assert response.status_code == 200
    assert response.data["results"] == []


@pytest.mark.django_db
def test_pending_approvals_single_active_user_tenant_sees_own_document(tenant_b, user_b, client_b):
    roles = _roles(tenant_b)
    ApprovalRule.objects.create(
        tenant=tenant_b, doc_type=ApprovalRule.DocType.JOURNAL_ENTRY, min_amount=0, required_role=roles["Accountant"]
    )
    # user_b (the tenant's only active user, an Owner) doesn't hold the
    # Accountant role the rule names — but approve() exempts a single-
    # active-user tenant from the role match entirely (3.15.1), so the
    # inbox must show this document to them too, not just approve() let
    # it through blindly.
    cash = Account.objects.get(tenant=tenant_b, system_key="CASH")
    sales = Account.objects.get(tenant=tenant_b, system_key="SALES")
    entry = create_manual_journal_entry(
        tenant=tenant_b, user=user_b, legal_entity=_branch(tenant_b), date=date(2026, 1, 5),
        line_specs=[
            {"account": cash, "debit_fc": Decimal("50.00"), "credit_fc": Decimal("0")},
            {"account": sales, "debit_fc": Decimal("0"), "credit_fc": Decimal("50.00")},
        ],
        currency="SAR", exchange_rate=Decimal("1"),
    )
    submit_journal_entry_for_approval(entry, user_b)

    response = client_b.get("/api/approvals/pending/")
    assert response.status_code == 200
    assert len(response.data["results"]) == 1
    assert response.data["results"][0]["id"] == str(entry.id)


class _StubRequest:
    def __init__(self, user, method):
        self.user = user
        self.method = method


class _StubApiViewNoAction:
    """A plain APIView never has `.action` (a DRF-ViewSet-only concept)
    — this stand-in deliberately omits it to reproduce exactly the
    shape that used to raise AttributeError inside has_permission()."""

    permission_map = {"view": "accounting.view", "manage": "assets.manage"}


@pytest.mark.django_db
def test_has_module_permission_derives_view_from_get_on_plain_apiview(tenant_a, user_a):
    # user_a is an Owner (conftest.py) — holds every permission.
    granted = HasModulePermission().has_permission(_StubRequest(user_a, "GET"), _StubApiViewNoAction())
    assert granted is True


@pytest.mark.django_db
def test_has_module_permission_derives_manage_from_post_on_plain_apiview(tenant_a, user_a):
    granted = HasModulePermission().has_permission(_StubRequest(user_a, "POST"), _StubApiViewNoAction())
    assert granted is True


@pytest.mark.django_db
def test_has_module_permission_denies_without_matching_permission(tenant_a):
    roles = _roles(tenant_a)
    sales_user = UserFactory(tenant=tenant_a, email="sales@has-module-permission.test")
    sales_user.roles.add(roles["Sales"])
    # Sales holds neither accounting.view nor assets.manage.
    assert HasModulePermission().has_permission(_StubRequest(sales_user, "GET"), _StubApiViewNoAction()) is False
    assert HasModulePermission().has_permission(_StubRequest(sales_user, "POST"), _StubApiViewNoAction()) is False


@pytest.mark.django_db
def test_tenant_isolation(tenant_a, tenant_b, client_a, client_b):
    response_a = client_a.get("/api/dashboard/summary/")
    assert response_a.status_code == 200
    response_b = client_b.get("/api/approvals/pending/")
    assert response_b.status_code == 200
    assert response_b.data["results"] == []
