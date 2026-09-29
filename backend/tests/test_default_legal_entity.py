"""Sprint 6.5.14: /auth/me/'s legal_entity_ids[0] used to be sorted
alphabetically by UUID string — arbitrary with respect to entity_type,
so a simplified-mode tenant's own documents could sit split across its
company/branch entities with nothing tying "the default" to either one
consistently (see docs/prompts/sprint-6.5.md §6.5.14 for the real-tenant
evidence this was built from). Covers:

1. default_legal_entity_id_for_user's determinism — the result must not
   depend on which entity happens to sort first by UUID string.
2. A brand-new simplified-mode user (CreateUserSerializer) must be able
   to see and approve the Owner's documents on BOTH the company and the
   branch entity, not just the branch.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.access.services import seed_default_roles
from apps.accounting.periods import seed_fiscal_year_for_tenant
from apps.accounting.services import (
    create_manual_journal_entry,
    seed_chart_of_accounts,
    seed_tax_codes_for_country,
    submit_journal_entry_for_approval,
)
from apps.approvals.models import ApprovalRule
from apps.organization.models import LegalEntity
from apps.organization.services import (
    create_default_legal_entities,
    default_legal_entity_id_for_user,
    get_accessible_entity_ids,
)

from .factories import TenantFactory, UserFactory


def _leaf_pair(tenant):
    from apps.accounting.models import Account

    return (
        Account.objects.get(tenant=tenant, system_key="CASH"),
        Account.objects.get(tenant=tenant, system_key="SALES"),
    )


@pytest.mark.django_db
def test_default_entity_is_deterministic_regardless_of_uuid_order():
    """Two tenants, each with a company + branch, but with the UUIDs
    deliberately assigned in opposite relative order — the old
    `sorted(str(eid) for eid in accessible_ids)[0]` pattern would pick
    a different *type* of entity in each case, purely because of UUID
    string ordering. default_legal_entity_id_for_user must pick the
    BRANCH in both cases."""
    # Tenant 1: company's UUID sorts BEFORE the branch's alphabetically
    # (the old code would have picked the company here — wrong).
    tenant1 = TenantFactory(subdomain="uuid-order-1")
    company1 = LegalEntity.objects.create(
        id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        tenant=tenant1, code="C1", name="Company One", entity_type=LegalEntity.Type.COMPANY,
    )
    branch1 = LegalEntity.objects.create(
        id=uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
        tenant=tenant1, code="B1", name="Branch One", entity_type=LegalEntity.Type.BRANCH, parent=company1,
    )
    owner1 = UserFactory(tenant=tenant1, email="owner@uuid-order-1.test")
    owner1.roles.add(seed_default_roles(tenant1)["Owner"])
    accessible1 = get_accessible_entity_ids(owner1)
    assert default_legal_entity_id_for_user(owner1, accessible1) == branch1.id

    # Tenant 2: branch's UUID sorts BEFORE the company's alphabetically
    # (the old code would have "accidentally" picked the branch here —
    # right by coincidence, not by design). Same deterministic result
    # either way proves the fix doesn't just flip the old bug's luck.
    tenant2 = TenantFactory(subdomain="uuid-order-2")
    company2 = LegalEntity.objects.create(
        id=uuid.UUID("ffffffff-ffff-ffff-ffff-fffffffffffe"),
        tenant=tenant2, code="C2", name="Company Two", entity_type=LegalEntity.Type.COMPANY,
    )
    branch2 = LegalEntity.objects.create(
        id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
        tenant=tenant2, code="B2", name="Branch Two", entity_type=LegalEntity.Type.BRANCH, parent=company2,
    )
    owner2 = UserFactory(tenant=tenant2, email="owner@uuid-order-2.test")
    owner2.roles.add(seed_default_roles(tenant2)["Owner"])
    accessible2 = get_accessible_entity_ids(owner2)
    assert default_legal_entity_id_for_user(owner2, accessible2) == branch2.id


@pytest.mark.django_db
def test_tenant_default_legal_entity_preference_wins_when_accessible():
    """When Tenant.default_legal_entity is set (e.g. the Owner picked
    the company on purpose in Settings → Company → Advanced) and the
    user can actually access it, it wins over the BRANCH-first
    fallback."""
    tenant = TenantFactory(subdomain="explicit-default")
    company = LegalEntity.objects.create(
        tenant=tenant, code="C1", name="Company", entity_type=LegalEntity.Type.COMPANY,
    )
    LegalEntity.objects.create(
        tenant=tenant, code="B1", name="Branch", entity_type=LegalEntity.Type.BRANCH, parent=company,
    )
    tenant.default_legal_entity = company
    tenant.save(update_fields=["default_legal_entity"])

    owner = UserFactory(tenant=tenant, email="owner@explicit-default.test")
    owner.roles.add(seed_default_roles(tenant)["Owner"])
    accessible = get_accessible_entity_ids(owner)
    assert default_legal_entity_id_for_user(owner, accessible) == company.id


@pytest.mark.django_db
def test_new_simplified_mode_user_sees_and_approves_owner_documents_on_company_and_branch():
    """The real-world Fatma scenario: the Owner's documents legitimately
    sit split across the company and branch entities. A brand-new
    simplified-mode user (created with no explicit entity_ids, per
    CreateUserSerializer's is_simplified_mode branch) must be granted
    both entities automatically — not just the branch — so they can see
    and approve everything, not just half of it."""
    tenant = TenantFactory(subdomain="fatma-like")
    create_default_legal_entities(tenant, tenant.name)
    seed_chart_of_accounts(tenant)
    seed_tax_codes_for_country(tenant, "SA")
    seed_fiscal_year_for_tenant(tenant, start_date=date(2026, 1, 1))
    company = LegalEntity.objects.get(tenant=tenant, entity_type=LegalEntity.Type.COMPANY)
    branch = LegalEntity.objects.get(tenant=tenant, entity_type=LegalEntity.Type.BRANCH)

    roles = seed_default_roles(tenant)
    owner = UserFactory(tenant=tenant, email="owner@fatma-like.test")
    owner.roles.add(roles["Owner"])

    ApprovalRule.objects.create(
        tenant=tenant, doc_type=ApprovalRule.DocType.JOURNAL_ENTRY, min_amount=0,
        required_role=roles["Accountant"],
    )
    cash, sales = _leaf_pair(tenant)

    entry_on_company = create_manual_journal_entry(
        tenant=tenant, user=owner, legal_entity=company, date=date(2026, 1, 5), memo="company-side entry",
        line_specs=[
            {"account": cash, "debit_fc": Decimal("10.00"), "credit_fc": Decimal("0")},
            {"account": sales, "debit_fc": Decimal("0"), "credit_fc": Decimal("10.00")},
        ],
        currency="SAR", exchange_rate=Decimal("1"),
    )
    entry_on_branch = create_manual_journal_entry(
        tenant=tenant, user=owner, legal_entity=branch, date=date(2026, 1, 6), memo="branch-side entry",
        line_specs=[
            {"account": cash, "debit_fc": Decimal("20.00"), "credit_fc": Decimal("0")},
            {"account": sales, "debit_fc": Decimal("0"), "credit_fc": Decimal("20.00")},
        ],
        currency="SAR", exchange_rate=Decimal("1"),
    )
    submit_journal_entry_for_approval(entry_on_company, owner)
    submit_journal_entry_for_approval(entry_on_branch, owner)
    assert entry_on_company.status == "pending_approval"
    assert entry_on_branch.status == "pending_approval"

    owner_client = APIClient()
    owner_client.force_authenticate(user=owner)
    created = owner_client.post(
        "/api/users/",
        {"email": "new-staff@fatma-like.test", "password": "NewStaffPass!2026"},
        format="json",
    )
    assert created.status_code == 201, created.data
    new_user_id = created.data["id"]

    assign = owner_client.post(
        f"/api/users/{new_user_id}/assign/", {"role_ids": [str(roles["Accountant"].id)]}, format="json",
    )
    assert assign.status_code == 200, assign.data

    from apps.accounts.models import User

    new_user = User.objects.get(id=new_user_id)
    accessible_ids = get_accessible_entity_ids(new_user)
    assert accessible_ids == {company.id, branch.id}

    new_client = APIClient()
    new_client.force_authenticate(user=new_user)

    listing = new_client.get("/api/journal-entries/")
    listed_ids = {row["id"] for row in listing.data["results"]}
    assert str(entry_on_company.id) in listed_ids
    assert str(entry_on_branch.id) in listed_ids

    approve_company = new_client.post(f"/api/journal-entries/{entry_on_company.id}/approve/")
    assert approve_company.status_code == 200, approve_company.data
    approve_branch = new_client.post(f"/api/journal-entries/{entry_on_branch.id}/approve/")
    assert approve_branch.status_code == 200, approve_branch.data
