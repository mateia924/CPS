"""Sprint 4.4 (docs/SYSTEM_ANALYSIS.md 3.15.1/3.15.2/3.15.9;
ARCH_REVIEW_1.md §3.2 debts #4/#5/#6): journal engine — states,
GenericFK source, reversal, reconciliation fields, cost-center split.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType

from apps.access.services import seed_default_roles
from apps.accounting.models import Account, JournalEntry, TaxCode
from apps.accounting.periods import seed_fiscal_year_for_tenant
from apps.accounting.services import (
    approve_journal_entry,
    compute_trial_balance,
    create_manual_journal_entry,
    post_invoice_journal_entry,
    post_journal_entry,
    reverse_journal_entry,
    seed_chart_of_accounts,
    seed_tax_codes_for_country,
    submit_journal_entry_for_approval,
)
from apps.approvals.models import ApprovalRule
from apps.organization.services import create_default_legal_entities
from apps.sales.models import Invoice
from apps.sales.services import create_invoice

from .factories import (
    CostCenterFactory,
    LegalEntityFactory,
    PartyFactory,
    ProductFactory,
    TenantFactory,
    UserFactory,
)


def _require_approval_for_every_jv(tenant, role):
    """Sprint 4.5: with no ApprovalRule, submit_for_approval auto-
    approves immediately (no gate at all) — tenants created directly
    via TenantFactory() (bypassing registration, which seeds this rule
    for real tenants) need it added explicitly for any test that
    exercises the "still needs a human to approve" path."""
    return ApprovalRule.objects.create(
        tenant=tenant, doc_type=ApprovalRule.DocType.JOURNAL_ENTRY, min_amount=0, required_role=role
    )


def _leaf_pair(tenant):
    cash = Account.objects.get(tenant=tenant, system_key="CASH")
    sales = Account.objects.get(tenant=tenant, system_key="SALES")
    return cash, sales


# ---------------------------------------------------------------------
# GenericFK source
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_invoice_posting_sets_a_real_genericfk_source(db):
    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    seed_fiscal_year_for_tenant(tenant, start_date=date(2026, 1, 1))
    seed_tax_codes_for_country(tenant, "SA")
    _company, entity = create_default_legal_entities(tenant, tenant.name)
    party = PartyFactory(tenant=tenant)
    product = ProductFactory(tenant=tenant, unit_price="50.00", tax_rate="0")
    tax_code_z = TaxCode.objects.get(tenant=tenant, code="Z")
    invoice = create_invoice(
        tenant=tenant, party=party, legal_entity=entity, issue_date=date(2026, 1, 1),
        line_inputs=[{"product": product, "quantity": Decimal("1"), "cost_center": None, "tax_code": tax_code_z}],
        currency="SAR", exchange_rate=Decimal("1"),
    )

    entry = post_invoice_journal_entry(invoice)

    assert entry.content_type == ContentType.objects.get_for_model(Invoice)
    assert entry.object_id == invoice.id
    assert entry.source == invoice


@pytest.mark.django_db
def test_invoice_posting_is_created_directly_as_posted_with_a_number(db):
    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    seed_fiscal_year_for_tenant(tenant, start_date=date(2026, 1, 1))
    seed_tax_codes_for_country(tenant, "SA")
    _company, entity = create_default_legal_entities(tenant, tenant.name)
    party = PartyFactory(tenant=tenant)
    product = ProductFactory(tenant=tenant, unit_price="50.00", tax_rate="0")
    tax_code_z = TaxCode.objects.get(tenant=tenant, code="Z")
    invoice = create_invoice(
        tenant=tenant, party=party, legal_entity=entity, issue_date=date(2026, 1, 1),
        line_inputs=[{"product": product, "quantity": Decimal("1"), "cost_center": None, "tax_code": tax_code_z}],
        currency="SAR", exchange_rate=Decimal("1"),
    )

    entry = post_invoice_journal_entry(invoice)

    assert entry.status == JournalEntry.Status.POSTED
    assert entry.number.startswith("JV-")


# ---------------------------------------------------------------------
# Cost-center split (ARCH_REVIEW_1.md debt #5)
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_invoice_with_two_cost_centers_generates_two_revenue_lines(db):
    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    seed_fiscal_year_for_tenant(tenant, start_date=date(2026, 1, 1))
    seed_tax_codes_for_country(tenant, "SA")
    _company, entity = create_default_legal_entities(tenant, tenant.name)
    party = PartyFactory(tenant=tenant)
    product_a = ProductFactory(tenant=tenant, unit_price="100.00", tax_rate="0")
    product_b = ProductFactory(tenant=tenant, unit_price="50.00", tax_rate="0")
    cc1 = CostCenterFactory(tenant=tenant)
    cc2 = CostCenterFactory(tenant=tenant)
    tax_code_z = TaxCode.objects.get(tenant=tenant, code="Z")

    invoice = create_invoice(
        tenant=tenant, party=party, legal_entity=entity, issue_date=date(2026, 1, 1),
        line_inputs=[
            {"product": product_a, "quantity": Decimal("1"), "cost_center": cc1, "tax_code": tax_code_z},
            {"product": product_b, "quantity": Decimal("1"), "cost_center": cc2, "tax_code": tax_code_z},
        ],
        currency="SAR", exchange_rate=Decimal("1"),
    )

    entry = post_invoice_journal_entry(invoice)
    revenue_lines = entry.lines.filter(account__system_key="SALES")

    assert revenue_lines.count() == 2
    by_cc = {line.cost_center_id: line.credit for line in revenue_lines}
    assert by_cc[cc1.id] == Decimal("100.00")
    assert by_cc[cc2.id] == Decimal("50.00")


@pytest.mark.django_db
def test_invoice_lines_without_cost_center_are_grouped_into_one_line(db):
    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    seed_fiscal_year_for_tenant(tenant, start_date=date(2026, 1, 1))
    seed_tax_codes_for_country(tenant, "SA")
    _company, entity = create_default_legal_entities(tenant, tenant.name)
    party = PartyFactory(tenant=tenant)
    product_a = ProductFactory(tenant=tenant, unit_price="10.00", tax_rate="0")
    product_b = ProductFactory(tenant=tenant, unit_price="20.00", tax_rate="0")
    tax_code_z = TaxCode.objects.get(tenant=tenant, code="Z")

    invoice = create_invoice(
        tenant=tenant, party=party, legal_entity=entity, issue_date=date(2026, 1, 1),
        line_inputs=[
            {"product": product_a, "quantity": Decimal("1"), "cost_center": None, "tax_code": tax_code_z},
            {"product": product_b, "quantity": Decimal("1"), "cost_center": None, "tax_code": tax_code_z},
        ],
        currency="SAR", exchange_rate=Decimal("1"),
    )

    entry = post_invoice_journal_entry(invoice)
    revenue_lines = entry.lines.filter(account__system_key="SALES")

    assert revenue_lines.count() == 1
    assert revenue_lines.first().credit == Decimal("30.00")


# ---------------------------------------------------------------------
# Trial balance: DRAFT excluded, POSTED included, REVERSED zeroes out.
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_draft_manual_entry_does_not_appear_in_trial_balance(db):
    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    seed_fiscal_year_for_tenant(tenant, start_date=date(2026, 1, 1))
    entity = LegalEntityFactory(tenant=tenant)
    owner = UserFactory(tenant=tenant)
    cash, sales = _leaf_pair(tenant)

    create_manual_journal_entry(
        tenant=tenant, user=owner, legal_entity=entity, date=date(2026, 1, 1),
        line_specs=[
            {"account": cash, "debit_fc": Decimal("100.00"), "credit_fc": Decimal("0")},
            {"account": sales, "debit_fc": Decimal("0"), "credit_fc": Decimal("100.00")},
        ],
        currency="SAR", exchange_rate=Decimal("1"),
    )

    result = compute_trial_balance(tenant)
    assert result["total_debit"] == Decimal("0")
    assert result["total_credit"] == Decimal("0")


@pytest.mark.django_db
def test_posted_manual_entry_appears_in_trial_balance_and_reversal_zeroes_it(db):
    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    seed_fiscal_year_for_tenant(tenant, start_date=date(2026, 1, 1))
    entity = LegalEntityFactory(tenant=tenant)
    roles = seed_default_roles(tenant)
    creator = UserFactory(tenant=tenant, email="creator@jv-tb.test")
    creator.roles.add(roles["Accountant"])
    approver = UserFactory(tenant=tenant, email="approver@jv-tb.test")
    approver.roles.add(roles["Owner"])
    _require_approval_for_every_jv(tenant, roles["Owner"])
    cash, sales = _leaf_pair(tenant)

    entry = create_manual_journal_entry(
        tenant=tenant, user=creator, legal_entity=entity, date=date(2026, 1, 1),
        line_specs=[
            {"account": cash, "debit_fc": Decimal("100.00"), "credit_fc": Decimal("0")},
            {"account": sales, "debit_fc": Decimal("0"), "credit_fc": Decimal("100.00")},
        ],
        currency="SAR", exchange_rate=Decimal("1"),
    )
    submit_journal_entry_for_approval(entry, creator)
    approve_journal_entry(entry, approver)
    post_journal_entry(entry, approver)

    posted_result = compute_trial_balance(tenant)
    assert posted_result["total_debit"] == Decimal("100.00")
    assert posted_result["total_debit"] == posted_result["total_credit"]

    reverse_journal_entry(entry, approver, "test reversal")
    entry.refresh_from_db()
    assert entry.status == JournalEntry.Status.REVERSED

    reversed_result = compute_trial_balance(tenant)
    cash_row = next(r for r in reversed_result["rows"] if r["account_id"] == cash.id)
    assert cash_row["balance"] == Decimal("0.00")
    assert reversed_result["total_debit"] == reversed_result["total_credit"]


# ---------------------------------------------------------------------
# Manual JV lifecycle + segregation of duties (3.15.9)
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_creator_cannot_approve_their_own_manual_entry(db):
    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    seed_fiscal_year_for_tenant(tenant, start_date=date(2026, 1, 1))
    entity = LegalEntityFactory(tenant=tenant)
    roles = seed_default_roles(tenant)
    # A second active user must exist for segregation of duties to
    # apply at all (single-user tenants are exempted, 3.15.1). A second
    # Owner specifically (not just any second user) — otherwise this
    # would qualify for 6.8's emergency-approval path (decision 18,
    # D4: no *other* active Owner at all) instead of the flat denial
    # this test means to check; that scenario has its own test below.
    creator = UserFactory(tenant=tenant, email="creator@jv-sod.test")
    creator.roles.add(roles["Owner"])
    UserFactory(tenant=tenant, email="other@jv-sod.test").roles.add(roles["Accountant"])
    UserFactory(tenant=tenant, email="other-owner@jv-sod.test").roles.add(roles["Owner"])
    _require_approval_for_every_jv(tenant, roles["Owner"])
    cash, sales = _leaf_pair(tenant)

    entry = create_manual_journal_entry(
        tenant=tenant, user=creator, legal_entity=entity, date=date(2026, 1, 1),
        line_specs=[
            {"account": cash, "debit_fc": Decimal("50.00"), "credit_fc": Decimal("0")},
            {"account": sales, "debit_fc": Decimal("0"), "credit_fc": Decimal("50.00")},
        ],
        currency="SAR", exchange_rate=Decimal("1"),
    )
    submit_journal_entry_for_approval(entry, creator)

    from django.core.exceptions import PermissionDenied

    with pytest.raises(PermissionDenied):
        approve_journal_entry(entry, creator)


@pytest.mark.django_db
def test_single_active_user_tenant_is_exempt_from_segregation_of_duties(db):
    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    seed_fiscal_year_for_tenant(tenant, start_date=date(2026, 1, 1))
    entity = LegalEntityFactory(tenant=tenant)
    roles = seed_default_roles(tenant)
    owner = UserFactory(tenant=tenant, email="solo-owner@jv-sod.test")
    owner.roles.add(roles["Owner"])
    _require_approval_for_every_jv(tenant, roles["Owner"])
    cash, sales = _leaf_pair(tenant)

    entry = create_manual_journal_entry(
        tenant=tenant, user=owner, legal_entity=entity, date=date(2026, 1, 1),
        line_specs=[
            {"account": cash, "debit_fc": Decimal("10.00"), "credit_fc": Decimal("0")},
            {"account": sales, "debit_fc": Decimal("0"), "credit_fc": Decimal("10.00")},
        ],
        currency="SAR", exchange_rate=Decimal("1"),
    )
    submit_journal_entry_for_approval(entry, owner)
    approve_journal_entry(entry, owner)  # must not raise — solo tenant
    entry.refresh_from_db()
    assert entry.status == JournalEntry.Status.APPROVED


@pytest.mark.django_db
def test_cannot_post_a_non_approved_entry(db):
    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    seed_fiscal_year_for_tenant(tenant, start_date=date(2026, 1, 1))
    entity = LegalEntityFactory(tenant=tenant)
    owner = UserFactory(tenant=tenant)
    cash, sales = _leaf_pair(tenant)

    entry = create_manual_journal_entry(
        tenant=tenant, user=owner, legal_entity=entity, date=date(2026, 1, 1),
        line_specs=[
            {"account": cash, "debit_fc": Decimal("10.00"), "credit_fc": Decimal("0")},
            {"account": sales, "debit_fc": Decimal("0"), "credit_fc": Decimal("10.00")},
        ],
        currency="SAR", exchange_rate=Decimal("1"),
    )

    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        post_journal_entry(entry, owner)


@pytest.mark.django_db
def test_manual_entry_numbering_uses_jv_prefix(db):
    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    seed_fiscal_year_for_tenant(tenant, start_date=date(2026, 1, 1))
    entity = LegalEntityFactory(tenant=tenant)
    owner = UserFactory(tenant=tenant)
    cash, sales = _leaf_pair(tenant)

    entry = create_manual_journal_entry(
        tenant=tenant, user=owner, legal_entity=entity, date=date(2026, 1, 1),
        line_specs=[
            {"account": cash, "debit_fc": Decimal("10.00"), "credit_fc": Decimal("0")},
            {"account": sales, "debit_fc": Decimal("0"), "credit_fc": Decimal("10.00")},
        ],
        currency="SAR", exchange_rate=Decimal("1"),
    )

    assert entry.number.startswith("JV-2026-")


# ---------------------------------------------------------------------
# API: /api/journal-entries/ create/submit/approve/post/reverse
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_manual_jv_full_lifecycle_via_api(db):
    from rest_framework.test import APIClient

    from apps.access.models import UserEntityAccess

    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    seed_fiscal_year_for_tenant(tenant, start_date=date(2026, 1, 1))
    entity = LegalEntityFactory(tenant=tenant)
    roles = seed_default_roles(tenant)
    creator = UserFactory(tenant=tenant, email="api-creator@jv-api.test")
    creator.roles.add(roles["Accountant"])
    # Accountant (non-Owner) only sees entities explicitly granted via
    # UserEntityAccess (organization/services.py:get_accessible_entity_ids)
    # — Owner bypasses this, which is why `approver` below doesn't need it.
    UserEntityAccess.objects.create(user=creator, legal_entity=entity)
    approver = UserFactory(tenant=tenant, email="api-approver@jv-api.test")
    approver.roles.add(roles["Owner"])
    _require_approval_for_every_jv(tenant, roles["Owner"])
    cash, sales = _leaf_pair(tenant)

    creator_client = APIClient()
    creator_client.force_authenticate(user=creator)
    approver_client = APIClient()
    approver_client.force_authenticate(user=approver)

    create = creator_client.post(
        "/api/journal-entries/",
        {
            "legal_entity": str(entity.id),
            "date": "2026-01-01",
            "memo": "test entry",
            "lines": [
                {"account": str(cash.id), "debit_fc": "20.00", "credit_fc": "0"},
                {"account": str(sales.id), "debit_fc": "0", "credit_fc": "20.00"},
            ],
        },
        format="json",
    )
    assert create.status_code == 201
    assert create.data["status"] == "draft"
    entry_id = create.data["id"]

    submit = creator_client.post(f"/api/journal-entries/{entry_id}/submit/")
    assert submit.status_code == 200
    assert submit.data["status"] == "pending_approval"

    self_approve = creator_client.post(f"/api/journal-entries/{entry_id}/approve/")
    assert self_approve.status_code == 403

    approve = approver_client.post(f"/api/journal-entries/{entry_id}/approve/")
    assert approve.status_code == 200
    assert approve.data["status"] == "approved"

    post = approver_client.post(f"/api/journal-entries/{entry_id}/post/")
    assert post.status_code == 200
    assert post.data["status"] == "posted"

    reverse = approver_client.post(f"/api/journal-entries/{entry_id}/reverse/", {"reason": "mistake"}, format="json")
    assert reverse.status_code == 201
    assert reverse.data["status"] == "posted"


@pytest.mark.django_db
def test_cannot_reverse_a_system_generated_entry_via_generic_action(db):
    from rest_framework.test import APIClient

    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    seed_fiscal_year_for_tenant(tenant, start_date=date(2026, 1, 1))
    _company, entity = create_default_legal_entities(tenant, tenant.name)
    roles = seed_default_roles(tenant)
    owner = UserFactory(tenant=tenant, email="owner@jv-void-guard.test")
    owner.roles.add(roles["Owner"])
    seed_tax_codes_for_country(tenant, "SA")
    party = PartyFactory(tenant=tenant)
    product = ProductFactory(tenant=tenant, unit_price="10.00", tax_rate="0")
    tax_code_z = TaxCode.objects.get(tenant=tenant, code="Z")
    invoice = create_invoice(
        tenant=tenant, party=party, legal_entity=entity, issue_date=date(2026, 1, 1),
        line_inputs=[{"product": product, "quantity": Decimal("1"), "cost_center": None, "tax_code": tax_code_z}],
        currency="SAR", exchange_rate=Decimal("1"),
    )
    entry = post_invoice_journal_entry(invoice)

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(f"/api/journal-entries/{entry.id}/reverse/", {"reason": "x"}, format="json")

    assert response.status_code == 400


@pytest.mark.django_db
def test_trial_balance_endpoint_totals_match(db):
    from rest_framework.test import APIClient

    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    seed_fiscal_year_for_tenant(tenant, start_date=date(2026, 1, 1))
    entity = LegalEntityFactory(tenant=tenant)
    roles = seed_default_roles(tenant)
    owner = UserFactory(tenant=tenant, email="owner@jv-trial.test")
    owner.roles.add(roles["Owner"])
    cash, sales = _leaf_pair(tenant)

    entry = create_manual_journal_entry(
        tenant=tenant, user=owner, legal_entity=entity, date=date(2026, 1, 1),
        line_specs=[
            {"account": cash, "debit_fc": Decimal("40.00"), "credit_fc": Decimal("0")},
            {"account": sales, "debit_fc": Decimal("0"), "credit_fc": Decimal("40.00")},
        ],
        currency="SAR", exchange_rate=Decimal("1"),
    )
    # No ApprovalRule configured for this tenant -> auto-approved on
    # submit (sprint 4.5's "لا قاعدة مطابقة = اعتماد تلقائي"); only
    # post_journal_entry (APPROVED -> POSTED) is still needed.
    submit_journal_entry_for_approval(entry, owner)
    entry.refresh_from_db()
    assert entry.status == JournalEntry.Status.APPROVED
    post_journal_entry(entry, owner)

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.get("/api/journal-entries/trial_balance/")

    assert response.status_code == 200
    assert response.data["total_debit"] == response.data["total_credit"] == "40.00"


# ---------------------------------------------------------------------
# Tenant isolation on new endpoints
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_journal_entry_actions_are_tenant_isolated(tenant_a, tenant_b, client_a):
    entity_b = LegalEntityFactory(tenant=tenant_b)
    owner_b = UserFactory(tenant=tenant_b)
    cash_b = Account.objects.get(tenant=tenant_b, system_key="CASH")
    sales_b = Account.objects.get(tenant=tenant_b, system_key="SALES")
    entry_b = create_manual_journal_entry(
        tenant=tenant_b, user=owner_b, legal_entity=entity_b, date=date(2026, 1, 1),
        line_specs=[
            {"account": cash_b, "debit_fc": Decimal("5.00"), "credit_fc": Decimal("0")},
            {"account": sales_b, "debit_fc": Decimal("0"), "credit_fc": Decimal("5.00")},
        ],
        currency="SAR", exchange_rate=Decimal("1"),
    )

    response = client_a.get(f"/api/journal-entries/{entry_b.id}/")
    assert response.status_code == 404

    submit = client_a.post(f"/api/journal-entries/{entry_b.id}/submit/")
    assert submit.status_code == 404


# ---------------------------------------------------------------------
# Sprint 6.6.5 (unified delete rule): a draft manual entry has no
# posted movement at all and gets a real "حذف" (soft delete); once
# posted, it stays 409 forever — reverse() is the only undo path.
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_delete_draft_journal_entry_soft_deletes(tenant_a, client_a):
    entity = LegalEntityFactory(tenant=tenant_a)
    cash, sales = _leaf_pair(tenant_a)
    create = client_a.post(
        "/api/journal-entries/",
        {
            "legal_entity": str(entity.id), "date": "2026-01-01", "memo": "draft to delete",
            "lines": [
                {"account": str(cash.id), "debit_fc": "20.00", "credit_fc": "0"},
                {"account": str(sales.id), "debit_fc": "0", "credit_fc": "20.00"},
            ],
        },
        format="json",
    )
    assert create.status_code == 201
    entry_id = create.data["id"]

    deleted = client_a.delete(f"/api/journal-entries/{entry_id}/")
    assert deleted.status_code == 204, deleted.data

    entry = JournalEntry.objects.get(id=entry_id)
    assert entry.deleted_at is not None
    assert client_a.get(f"/api/journal-entries/{entry_id}/").status_code == 404


@pytest.mark.django_db
def test_delete_posted_journal_entry_returns_409(tenant_a, client_a):
    entity = LegalEntityFactory(tenant=tenant_a)
    cash, sales = _leaf_pair(tenant_a)
    create = client_a.post(
        "/api/journal-entries/",
        {
            "legal_entity": str(entity.id), "date": "2026-01-01", "memo": "to post",
            "lines": [
                {"account": str(cash.id), "debit_fc": "20.00", "credit_fc": "0"},
                {"account": str(sales.id), "debit_fc": "0", "credit_fc": "20.00"},
            ],
        },
        format="json",
    )
    entry_id = create.data["id"]
    # No tenant ApprovalRule is seeded in this fixture, so submit
    # auto-approves immediately ("لا قاعدة مطابقة = اعتماد تلقائي").
    assert client_a.post(f"/api/journal-entries/{entry_id}/submit/").status_code == 200
    assert client_a.post(f"/api/journal-entries/{entry_id}/post/").status_code == 200

    deleted = client_a.delete(f"/api/journal-entries/{entry_id}/")
    assert deleted.status_code == 409, deleted.data


# ---------------------------------------------------------------------
# Sprint 6.6.5 (§6.2 addition): a still-DRAFT manual entry's own page
# can re-save its whole line set, generalizing the exact pattern
# OpeningBalanceViewSet.lines already had since 6.6.3d.
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_patch_lines_on_draft_journal_entry_replaces_them(tenant_a, client_a):
    entity = LegalEntityFactory(tenant=tenant_a)
    cash, sales = _leaf_pair(tenant_a)
    create = client_a.post(
        "/api/journal-entries/",
        {
            "legal_entity": str(entity.id), "date": "2026-01-01", "memo": "draft",
            "lines": [
                {"account": str(cash.id), "debit_fc": "20.00", "credit_fc": "0"},
                {"account": str(sales.id), "debit_fc": "0", "credit_fc": "20.00"},
            ],
        },
        format="json",
    )
    entry_id = create.data["id"]

    response = client_a.patch(
        f"/api/journal-entries/{entry_id}/lines/",
        {
            "lines": [
                {"account": str(cash.id), "debit_fc": "50.00", "credit_fc": "0"},
                {"account": str(sales.id), "debit_fc": "0", "credit_fc": "50.00"},
            ]
        },
        format="json",
    )
    assert response.status_code == 200, response.data
    amounts = {line["account_code"]: (line["debit"], line["credit"]) for line in response.data["lines"]}
    assert amounts[cash.code] == ("50.00", "0.00")


@pytest.mark.django_db
def test_patch_lines_on_posted_journal_entry_is_rejected(tenant_a, client_a):
    entity = LegalEntityFactory(tenant=tenant_a)
    cash, sales = _leaf_pair(tenant_a)
    create = client_a.post(
        "/api/journal-entries/",
        {
            "legal_entity": str(entity.id), "date": "2026-01-01", "memo": "to post",
            "lines": [
                {"account": str(cash.id), "debit_fc": "20.00", "credit_fc": "0"},
                {"account": str(sales.id), "debit_fc": "0", "credit_fc": "20.00"},
            ],
        },
        format="json",
    )
    entry_id = create.data["id"]
    assert client_a.post(f"/api/journal-entries/{entry_id}/submit/").status_code == 200
    assert client_a.post(f"/api/journal-entries/{entry_id}/post/").status_code == 200

    response = client_a.patch(
        f"/api/journal-entries/{entry_id}/lines/",
        {
            "lines": [
                {"account": str(cash.id), "debit_fc": "99.00", "credit_fc": "0"},
                {"account": str(sales.id), "debit_fc": "0", "credit_fc": "99.00"},
            ]
        },
        format="json",
    )
    assert response.status_code == 400, response.data


# ---------------------------------------------------------------------
# CFO_REVIEW_1 C4: every state transition locks the row (select_for_
# update) inside its own transaction before re-checking status — two
# concurrent "post" requests for the same entry must never both
# succeed.
# ---------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_concurrent_post_requests_only_one_succeeds():
    import threading

    from django.db import connection

    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    seed_fiscal_year_for_tenant(tenant, start_date=date(2026, 1, 1))
    entity = LegalEntityFactory(tenant=tenant)
    roles = seed_default_roles(tenant)
    creator = UserFactory(tenant=tenant, email="creator@concurrent-post.test")
    creator.roles.add(roles["Accountant"])
    approver = UserFactory(tenant=tenant, email="approver@concurrent-post.test")
    approver.roles.add(roles["Owner"])
    _require_approval_for_every_jv(tenant, roles["Owner"])
    cash, sales = _leaf_pair(tenant)

    entry = create_manual_journal_entry(
        tenant=tenant, user=creator, legal_entity=entity, date=date(2026, 1, 1),
        line_specs=[
            {"account": cash, "debit_fc": Decimal("50.00"), "credit_fc": Decimal("0")},
            {"account": sales, "debit_fc": Decimal("0"), "credit_fc": Decimal("50.00")},
        ],
        currency="SAR", exchange_rate=Decimal("1"),
    )
    submit_journal_entry_for_approval(entry, creator)
    approve_journal_entry(entry, approver)
    entry.refresh_from_db()
    assert entry.status == "approved"

    results = []
    errors = []

    def worker():
        # Each thread re-fetches its own instance — same setup as the
        # real view (self.get_object() per request), not a shared
        # in-memory object racing on the same Python attribute.
        own_copy = JournalEntry.objects.get(pk=entry.pk)
        try:
            post_journal_entry(own_copy, approver)
            results.append("posted")
        except Exception as exc:  # noqa: BLE001 — surfaced via `errors`
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results == ["posted"]
    assert len(errors) == 1
    entry.refresh_from_db()
    assert entry.status == "posted"


@pytest.mark.django_db
def test_historical_rows_keep_content_type_null_forever(db):
    """Sprint 7.2.7 (§8.7, owner decision 2026-10-07): "نقل ب" was
    scrapped entirely — content_type/object_id are never backfilled
    for a historical row whose produced_by is one of the four values
    "نقل ب" used to try to cover (recurring/asset_disposal/
    opening_balance/asset_disposal_correction). The real reason: that
    backfill was a direct UPDATE on an already-POSTED JournalEntry —
    forbidden categorically by protect_posted_journal_entry()
    (0019_posted_entry_protection_triggers) — and the trigger caught
    it for real on staging before it ever reached production (§11,
    2026-10-07).

    This test guards the decision positively, not by absence: it
    builds rows in exactly the historical shape (produced_by set,
    source_type/source_id the frozen pre-7.2.7a trail, content_type/
    object_id null, status POSTED) and asserts the schema accepts
    them as a legitimate, permanent state. If anyone later tries to
    "complete" the reference — a new CheckConstraint, a NOT NULL on
    content_type, a trigger requiring it whenever produced_by is one
    of these four — creating a row in this shape starts failing
    immediately, in this test, in CI. Not discovered later on staging
    or production.

    Updated 2026-10-08 (Deploy ب): the freeze
    (0042_freeze_source_type_source_id) now rejects any INSERT that
    sets source_type/source_id at all — by design, that's its whole
    job. Seeding this test's own historical-shaped fixture needs the
    same bypass used to prove the freeze itself
    (test_db_triggers.py): session_replication_role = replica for the
    one seeding statement, reset immediately after. This is the only
    way left to construct the exact shape real pre-freeze rows are
    in — which is exactly why the freeze protects it.
    """
    from django.db import connection

    tenant = TenantFactory()
    _company, entity = create_default_legal_entities(tenant, tenant.name)

    historical_values = [
        JournalEntry.ProducedBy.RECURRING,
        JournalEntry.ProducedBy.ASSET_DISPOSAL,
        JournalEntry.ProducedBy.OPENING_BALANCE,
        JournalEntry.ProducedBy.ASSET_DISPOSAL_CORRECTION,
    ]
    for value in historical_values:
        entry = JournalEntry.objects.create(
            tenant=tenant, legal_entity=entity, date=date(2026, 1, 1),
            status=JournalEntry.Status.POSTED, produced_by=value,
        )
        with connection.cursor() as cursor:
            cursor.execute("SET session_replication_role = replica")
            try:
                cursor.execute(
                    "UPDATE accounting_journalentry SET source_type = %s, source_id = %s WHERE id = %s",
                    [value, str(uuid.uuid4()), str(entry.id)],
                )
            finally:
                cursor.execute("SET session_replication_role = DEFAULT")
        entry.refresh_from_db()
        assert entry.produced_by == value
        assert entry.source_type == value
        assert entry.content_type is None
        assert entry.object_id is None
