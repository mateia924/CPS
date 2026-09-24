"""Sprint 6.8 (decision 18, CFO_REVIEW_1 §8 D4): "الاعتماد الاضطراري" —
in a tenant where the document's creator is the only user holding the
document's required approval role at all, an Owner may approve their
own document by providing a mandatory reason. AuditLog.after carries
{"is_emergency_approval": True, "emergency_reason": ...}, surfaced via
GET /api/approvals/emergency/. The instant a second user holds that
role, this path closes and the ordinary segregation-of-duties 403
denial applies (test_journal_engine.py's
test_creator_cannot_approve_their_own_manual_entry already covers that
directly at the service layer; this file re-asserts it through the API
for completeness, per the block's own acceptance-test list).
"""

import pytest

from apps.access.models import Role
from apps.access.services import seed_default_roles
from apps.accounting.models import Account
from apps.approvals.models import ApprovalRule
from apps.organization.models import LegalEntity

from .factories import UserFactory


def _roles(tenant):
    # user_a/user_b (conftest.py) already seed roles for their own
    # tenant — calling seed_default_roles again here would duplicate
    # the system rows and violate unique_role_name_per_tenant.
    existing = {r.name: r for r in Role.objects.filter(tenant=tenant, is_system=True)}
    return existing or seed_default_roles(tenant)


def _require_approval_for_every_jv(tenant, role):
    return ApprovalRule.objects.create(
        tenant=tenant, doc_type=ApprovalRule.DocType.JOURNAL_ENTRY, min_amount=0, required_role=role
    )


def _branch(tenant):
    return LegalEntity.objects.get(tenant=tenant, entity_type=LegalEntity.Type.BRANCH)


def _leaf_pair(tenant):
    cash = Account.objects.get(tenant=tenant, system_key="CASH")
    sales = Account.objects.get(tenant=tenant, system_key="SALES")
    return cash, sales


def _create_and_submit_entry(client, tenant):
    cash, sales = _leaf_pair(tenant)
    payload = {
        "legal_entity": str(_branch(tenant).id), "date": "2026-01-05",
        "lines": [
            {"account": str(cash.id), "debit_fc": "50.00", "credit_fc": "0"},
            {"account": str(sales.id), "debit_fc": "0", "credit_fc": "50.00"},
        ],
    }
    created = client.post("/api/journal-entries/", payload, format="json")
    assert created.status_code == 201, created.data
    submitted = client.post(f"/api/journal-entries/{created.data['id']}/submit/")
    assert submitted.status_code == 200, submitted.data
    return created.data["id"]


@pytest.mark.django_db
def test_owner_approves_own_entry_with_emergency_reason(tenant_a, user_a, client_a):
    roles = _roles(tenant_a)
    _require_approval_for_every_jv(tenant_a, roles["Owner"])
    UserFactory(tenant=tenant_a, email="accountant@emergency.test").roles.add(roles["Accountant"])

    entry_id = _create_and_submit_entry(client_a, tenant_a)

    no_reason = client_a.post(f"/api/journal-entries/{entry_id}/approve/")
    assert no_reason.status_code == 400, no_reason.data

    with_reason = client_a.post(
        f"/api/journal-entries/{entry_id}/approve/",
        {"emergency_reason": "لا يوجد معتمد آخر متاح اليوم"}, format="json",
    )
    assert with_reason.status_code == 200, with_reason.data

    emergency = client_a.get("/api/approvals/emergency/")
    assert emergency.status_code == 200, emergency.data
    assert any(str(item["target_id"]) == entry_id for item in emergency.data)
    match = next(item for item in emergency.data if str(item["target_id"]) == entry_id)
    assert match["emergency_reason"] == "لا يوجد معتمد آخر متاح اليوم"


@pytest.mark.django_db
def test_second_owner_present_falls_back_to_ordinary_denial(tenant_a, user_a, client_a):
    roles = _roles(tenant_a)
    _require_approval_for_every_jv(tenant_a, roles["Owner"])
    UserFactory(tenant=tenant_a, email="accountant@emergency.test").roles.add(roles["Accountant"])
    UserFactory(tenant=tenant_a, email="other-owner@emergency.test").roles.add(roles["Owner"])

    entry_id = _create_and_submit_entry(client_a, tenant_a)

    denied = client_a.post(f"/api/journal-entries/{entry_id}/approve/")
    assert denied.status_code == 403, denied.data


@pytest.mark.django_db
def test_tenant_isolation(tenant_a, tenant_b, client_b):
    roles = _roles(tenant_a)
    _require_approval_for_every_jv(tenant_a, roles["Owner"])
    response = client_b.get("/api/approvals/emergency/")
    assert response.status_code == 200
    assert response.data == []
