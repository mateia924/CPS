"""Sprint 4.5 (docs/SYSTEM_ANALYSIS.md 3.15.1): approval engine,
segregation of duties, approval inbox."""

from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.access.services import seed_default_roles
from apps.accounting.models import Account, TaxCode
from apps.accounting.periods import seed_fiscal_year_for_tenant
from apps.accounting.services import (
    create_manual_journal_entry,
    seed_chart_of_accounts,
    seed_tax_codes_for_country,
    submit_journal_entry_for_approval,
)
from apps.approvals.models import ApprovalRule
from apps.organization.services import create_default_legal_entities
from apps.sales.models import Invoice
from apps.sales.services import create_invoice, issue_invoice

from .factories import LegalEntityFactory, PartyFactory, ProductFactory, TenantFactory, UserFactory


def _leaf_pair(tenant):
    cash = Account.objects.get(tenant=tenant, system_key="CASH")
    sales = Account.objects.get(tenant=tenant, system_key="SALES")
    return cash, sales


# ---------------------------------------------------------------------
# Literal spec test: "قاعدة JV > 10,000 تتطلب OWNER؛ محاسب ينشئ قيد
# 20,000 ويحاول اعتماده → 403؛ Owner يعتمد → POSTED"
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_tiered_rule_jv_over_10000_requires_owner_approval(db):
    from rest_framework.test import APIClient

    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    seed_fiscal_year_for_tenant(tenant, start_date=date(2026, 1, 1))
    entity = LegalEntityFactory(tenant=tenant)
    roles = seed_default_roles(tenant)
    ApprovalRule.objects.create(
        tenant=tenant, doc_type=ApprovalRule.DocType.JOURNAL_ENTRY,
        min_amount=Decimal("10000"), required_role=roles["Owner"],
    )
    from apps.access.models import UserEntityAccess

    accountant = UserFactory(tenant=tenant, email="accountant@jv-tier.test")
    accountant.roles.add(roles["Accountant"])
    # Accountant (non-Owner) only sees entities explicitly granted via
    # UserEntityAccess (organization/services.py:get_accessible_entity_ids).
    UserEntityAccess.objects.create(user=accountant, legal_entity=entity)
    owner = UserFactory(tenant=tenant, email="owner@jv-tier.test")
    owner.roles.add(roles["Owner"])
    cash, sales = _leaf_pair(tenant)

    entry = create_manual_journal_entry(
        tenant=tenant, user=accountant, legal_entity=entity, date=date(2026, 1, 1),
        line_specs=[
            {"account": cash, "debit_fc": Decimal("20000.00"), "credit_fc": Decimal("0")},
            {"account": sales, "debit_fc": Decimal("0"), "credit_fc": Decimal("20000.00")},
        ],
        currency="SAR", exchange_rate=Decimal("1"),
    )
    submit_journal_entry_for_approval(entry, accountant)
    entry.refresh_from_db()
    assert entry.status == "pending_approval"  # a matching rule exists -> not auto-approved

    accountant_client = APIClient()
    accountant_client.force_authenticate(user=accountant)
    self_attempt = accountant_client.post(f"/api/journal-entries/{entry.id}/approve/")
    assert self_attempt.status_code == 403

    owner_client = APIClient()
    owner_client.force_authenticate(user=owner)
    approve = owner_client.post(f"/api/journal-entries/{entry.id}/approve/")
    assert approve.status_code == 200
    assert approve.data["status"] == "approved"

    post = owner_client.post(f"/api/journal-entries/{entry.id}/post/")
    assert post.status_code == 200
    assert post.data["status"] == "posted"


@pytest.mark.django_db
def test_jv_below_threshold_does_not_require_owner(db):
    """Same tenant/rule as above, but a smaller entry a plain
    Accountant-tier rule (min_amount=0) can self-clear — proves the
    tiered matching picks the highest qualifying rule, not just any."""
    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    seed_fiscal_year_for_tenant(tenant, start_date=date(2026, 1, 1))
    entity = LegalEntityFactory(tenant=tenant)
    roles = seed_default_roles(tenant)
    ApprovalRule.objects.create(
        tenant=tenant, doc_type=ApprovalRule.DocType.JOURNAL_ENTRY,
        min_amount=Decimal("10000"), required_role=roles["Owner"],
    )
    ApprovalRule.objects.create(
        tenant=tenant, doc_type=ApprovalRule.DocType.JOURNAL_ENTRY,
        min_amount=0, required_role=roles["Accountant"],
    )
    from apps.access.models import UserEntityAccess

    creator = UserFactory(tenant=tenant, email="creator@jv-tier-low.test")
    creator.roles.add(roles["Owner"])
    approver = UserFactory(tenant=tenant, email="approver@jv-tier-low.test")
    approver.roles.add(roles["Accountant"])
    UserEntityAccess.objects.create(user=approver, legal_entity=entity)
    cash, sales = _leaf_pair(tenant)

    entry = create_manual_journal_entry(
        tenant=tenant, user=creator, legal_entity=entity, date=date(2026, 1, 1),
        line_specs=[
            {"account": cash, "debit_fc": Decimal("500.00"), "credit_fc": Decimal("0")},
            {"account": sales, "debit_fc": Decimal("0"), "credit_fc": Decimal("500.00")},
        ],
        currency="SAR", exchange_rate=Decimal("1"),
    )
    submit_journal_entry_for_approval(entry, creator)

    client = APIClient()
    client.force_authenticate(user=approver)
    response = client.post(f"/api/journal-entries/{entry.id}/approve/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_reject_without_reason_returns_400(db):
    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    seed_fiscal_year_for_tenant(tenant, start_date=date(2026, 1, 1))
    entity = LegalEntityFactory(tenant=tenant)
    roles = seed_default_roles(tenant)
    ApprovalRule.objects.create(
        tenant=tenant, doc_type=ApprovalRule.DocType.JOURNAL_ENTRY, min_amount=0, required_role=roles["Owner"],
    )
    creator = UserFactory(tenant=tenant, email="creator@jv-reject.test")
    creator.roles.add(roles["Accountant"])
    owner = UserFactory(tenant=tenant, email="owner@jv-reject.test")
    owner.roles.add(roles["Owner"])
    cash, sales = _leaf_pair(tenant)

    entry = create_manual_journal_entry(
        tenant=tenant, user=creator, legal_entity=entity, date=date(2026, 1, 1),
        line_specs=[
            {"account": cash, "debit_fc": Decimal("5.00"), "credit_fc": Decimal("0")},
            {"account": sales, "debit_fc": Decimal("0"), "credit_fc": Decimal("5.00")},
        ],
        currency="SAR", exchange_rate=Decimal("1"),
    )
    submit_journal_entry_for_approval(entry, creator)

    client = APIClient()
    client.force_authenticate(user=owner)
    no_reason = client.post(f"/api/journal-entries/{entry.id}/reject/", {}, format="json")
    assert no_reason.status_code == 400

    with_reason = client.post(f"/api/journal-entries/{entry.id}/reject/", {"reason": "wrong account"}, format="json")
    assert with_reason.status_code == 200
    assert with_reason.data["status"] == "draft"


# ---------------------------------------------------------------------
# Invoice: small-client behavior unchanged, blocked-then-inbox-approved
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_invoice_with_no_rule_issues_immediately_small_client_unchanged(db):
    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    seed_fiscal_year_for_tenant(tenant, start_date=date(2026, 1, 1))
    seed_tax_codes_for_country(tenant, "SA")
    _company, entity = create_default_legal_entities(tenant, tenant.name)
    roles = seed_default_roles(tenant)
    owner = UserFactory(tenant=tenant, email="owner@inv-small.test")
    owner.roles.add(roles["Owner"])
    party = PartyFactory(tenant=tenant)
    product = ProductFactory(tenant=tenant, unit_price="10.00", tax_rate="0")
    tax_code_z = TaxCode.objects.get(tenant=tenant, code="Z")
    invoice = create_invoice(
        tenant=tenant, party=party, legal_entity=entity, issue_date=date(2026, 1, 1),
        line_inputs=[{"product": product, "quantity": Decimal("1"), "cost_center": None, "tax_code": tax_code_z}],
        currency="SAR", exchange_rate=Decimal("1"), created_by=owner,
    )

    issued = issue_invoice(invoice, owner)

    assert issued.status == Invoice.Status.ISSUED


@pytest.mark.django_db
def test_invoice_blocked_by_rule_stays_pending_then_inbox_approval_issues_it(db):
    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    seed_fiscal_year_for_tenant(tenant, start_date=date(2026, 1, 1))
    seed_tax_codes_for_country(tenant, "SA")
    _company, entity = create_default_legal_entities(tenant, tenant.name)
    roles = seed_default_roles(tenant)
    ApprovalRule.objects.create(
        tenant=tenant, doc_type=ApprovalRule.DocType.INVOICE, min_amount=0, required_role=roles["Owner"],
    )
    from apps.access.models import UserEntityAccess

    creator = UserFactory(tenant=tenant, email="creator@inv-blocked.test")
    creator.roles.add(roles["Accountant"])
    UserEntityAccess.objects.create(user=creator, legal_entity=entity)
    owner = UserFactory(tenant=tenant, email="owner@inv-blocked.test")
    owner.roles.add(roles["Owner"])
    party = PartyFactory(tenant=tenant)
    product = ProductFactory(tenant=tenant, unit_price="10.00", tax_rate="0")
    tax_code_z = TaxCode.objects.get(tenant=tenant, code="Z")
    invoice = create_invoice(
        tenant=tenant, party=party, legal_entity=entity, issue_date=date(2026, 1, 1),
        line_inputs=[{"product": product, "quantity": Decimal("1"), "cost_center": None, "tax_code": tax_code_z}],
        currency="SAR", exchange_rate=Decimal("1"), created_by=creator,
    )

    client = APIClient()
    client.force_authenticate(user=creator)
    blocked = client.post(f"/api/invoices/{invoice.id}/issue/")
    assert blocked.status_code == 200
    assert blocked.data["status"] == "pending_approval"

    owner_client = APIClient()
    owner_client.force_authenticate(user=owner)
    approved = owner_client.post(f"/api/invoices/{invoice.id}/approve/")
    assert approved.status_code == 200
    assert approved.data["status"] == "issued"


@pytest.mark.django_db
def test_invoice_reject_sends_it_back_to_draft(db):
    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    seed_fiscal_year_for_tenant(tenant, start_date=date(2026, 1, 1))
    seed_tax_codes_for_country(tenant, "SA")
    _company, entity = create_default_legal_entities(tenant, tenant.name)
    roles = seed_default_roles(tenant)
    ApprovalRule.objects.create(
        tenant=tenant, doc_type=ApprovalRule.DocType.INVOICE, min_amount=0, required_role=roles["Owner"],
    )
    from apps.access.models import UserEntityAccess

    creator = UserFactory(tenant=tenant, email="creator@inv-reject.test")
    creator.roles.add(roles["Accountant"])
    UserEntityAccess.objects.create(user=creator, legal_entity=entity)
    owner = UserFactory(tenant=tenant, email="owner@inv-reject.test")
    owner.roles.add(roles["Owner"])
    party = PartyFactory(tenant=tenant)
    product = ProductFactory(tenant=tenant, unit_price="10.00", tax_rate="0")
    tax_code_z = TaxCode.objects.get(tenant=tenant, code="Z")
    invoice = create_invoice(
        tenant=tenant, party=party, legal_entity=entity, issue_date=date(2026, 1, 1),
        line_inputs=[{"product": product, "quantity": Decimal("1"), "cost_center": None, "tax_code": tax_code_z}],
        currency="SAR", exchange_rate=Decimal("1"), created_by=creator,
    )
    client = APIClient()
    client.force_authenticate(user=creator)
    issued = client.post(f"/api/invoices/{invoice.id}/issue/")
    assert issued.status_code == 200
    assert issued.data["status"] == "pending_approval"

    owner_client = APIClient()
    owner_client.force_authenticate(user=owner)
    rejected = owner_client.post(f"/api/invoices/{invoice.id}/reject/", {"reason": "wrong amount"}, format="json")

    assert rejected.status_code == 200
    assert rejected.data["status"] == "draft"


# ---------------------------------------------------------------------
# صندوق الاعتماد: /api/approvals/pending/
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_pending_approvals_inbox_shows_matching_role_only(db):
    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    seed_fiscal_year_for_tenant(tenant, start_date=date(2026, 1, 1))
    entity = LegalEntityFactory(tenant=tenant)
    roles = seed_default_roles(tenant)
    ApprovalRule.objects.create(
        tenant=tenant, doc_type=ApprovalRule.DocType.JOURNAL_ENTRY, min_amount=0, required_role=roles["Owner"],
    )
    creator = UserFactory(tenant=tenant, email="creator@inbox.test")
    creator.roles.add(roles["Accountant"])
    owner = UserFactory(tenant=tenant, email="owner@inbox.test")
    owner.roles.add(roles["Owner"])
    viewer = UserFactory(tenant=tenant, email="viewer@inbox.test")
    viewer.roles.add(roles["Viewer"])
    cash, sales = _leaf_pair(tenant)

    entry = create_manual_journal_entry(
        tenant=tenant, user=creator, legal_entity=entity, date=date(2026, 1, 1),
        line_specs=[
            {"account": cash, "debit_fc": Decimal("5.00"), "credit_fc": Decimal("0")},
            {"account": sales, "debit_fc": Decimal("0"), "credit_fc": Decimal("5.00")},
        ],
        currency="SAR", exchange_rate=Decimal("1"),
    )
    submit_journal_entry_for_approval(entry, creator)

    owner_client = APIClient()
    owner_client.force_authenticate(user=owner)
    owner_inbox = owner_client.get("/api/approvals/pending/")
    assert owner_inbox.status_code == 200
    assert len(owner_inbox.data) == 1
    assert owner_inbox.data[0]["doc_type"] == "journal_entry"

    viewer_client = APIClient()
    viewer_client.force_authenticate(user=viewer)
    viewer_inbox = viewer_client.get("/api/approvals/pending/")
    assert viewer_inbox.data == []


@pytest.mark.django_db
def test_pending_approvals_inbox_is_tenant_isolated(tenant_a, tenant_b, client_a):
    roles_b = seed_default_roles(tenant_b)
    from apps.access.services import (
        seed_default_roles as _sdr,  # noqa: F401 (already imported above; explicit for clarity)
    )

    entity_b = LegalEntityFactory(tenant=tenant_b)
    creator_b = UserFactory(tenant=tenant_b, email="creator@inbox-iso-b.test")
    creator_b.roles.add(roles_b["Accountant"])
    ApprovalRule.objects.create(
        tenant=tenant_b, doc_type=ApprovalRule.DocType.JOURNAL_ENTRY, min_amount=0, required_role=roles_b["Owner"],
    )
    cash_b = Account.objects.get(tenant=tenant_b, system_key="CASH")
    sales_b = Account.objects.get(tenant=tenant_b, system_key="SALES")
    entry_b = create_manual_journal_entry(
        tenant=tenant_b, user=creator_b, legal_entity=entity_b, date=date(2026, 1, 1),
        line_specs=[
            {"account": cash_b, "debit_fc": Decimal("5.00"), "credit_fc": Decimal("0")},
            {"account": sales_b, "debit_fc": Decimal("0"), "credit_fc": Decimal("5.00")},
        ],
        currency="SAR", exchange_rate=Decimal("1"),
    )
    submit_journal_entry_for_approval(entry_b, creator_b)

    response = client_a.get("/api/approvals/pending/")
    assert response.status_code == 200
    assert response.data == []


# ---------------------------------------------------------------------
# قواعد الاعتماد screen: /api/approval-rules/
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_approval_rule_crud_and_permissions(db):
    tenant = TenantFactory()
    roles = seed_default_roles(tenant)
    owner = UserFactory(tenant=tenant, email="owner@rules-screen.test")
    owner.roles.add(roles["Owner"])
    accountant = UserFactory(tenant=tenant, email="accountant@rules-screen.test")
    accountant.roles.add(roles["Accountant"])

    owner_client = APIClient()
    owner_client.force_authenticate(user=owner)
    create = owner_client.post(
        "/api/approval-rules/",
        {"doc_type": "invoice", "min_amount": "5000.00", "required_role": str(roles["Owner"].id)},
        format="json",
    )
    assert create.status_code == 201

    accountant_client = APIClient()
    accountant_client.force_authenticate(user=accountant)
    # Accountant has approvals.view (list) but not approvals.manage (create).
    listing = accountant_client.get("/api/approval-rules/")
    assert listing.status_code == 200
    forbidden_create = accountant_client.post(
        "/api/approval-rules/",
        {"doc_type": "invoice", "min_amount": "1.00", "required_role": str(roles["Accountant"].id)},
        format="json",
    )
    assert forbidden_create.status_code == 403


@pytest.mark.django_db
def test_approval_rules_are_tenant_isolated(tenant_a, tenant_b, client_a):
    roles_b = seed_default_roles(tenant_b)
    rule_b = ApprovalRule.objects.create(
        tenant=tenant_b, doc_type=ApprovalRule.DocType.INVOICE, min_amount=0, required_role=roles_b["Owner"],
    )

    response = client_a.get(f"/api/approval-rules/{rule_b.id}/")
    assert response.status_code == 404


# ---------------------------------------------------------------------
# Sprint 5.3/5.6: vouchers join the same approval engine and the same
# inbox (apps.approvals.views.PendingApprovalsView) — this was missing
# from block 5.3's own test coverage (no approval-rule scenario was
# exercised for vouchers there) and PendingApprovalsView itself only
# looped over JournalEntry/Invoice until this fix.
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_voucher_blocked_by_rule_appears_in_inbox_and_creator_cannot_self_approve(db):
    from apps.access.models import UserEntityAccess

    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    seed_fiscal_year_for_tenant(tenant, start_date=date(2026, 1, 1))
    seed_tax_codes_for_country(tenant, "SA")
    _company, entity = create_default_legal_entities(tenant, tenant.name)
    roles = seed_default_roles(tenant)
    ApprovalRule.objects.create(
        tenant=tenant, doc_type=ApprovalRule.DocType.VOUCHER_PAYMENT, min_amount="5000.00",
        required_role=roles["Owner"],
    )

    creator = UserFactory(tenant=tenant, email="creator@voucher-inbox.test")
    creator.roles.add(roles["Accountant"])
    UserEntityAccess.objects.create(user=creator, legal_entity=entity)
    owner = UserFactory(tenant=tenant, email="owner@voucher-inbox.test")
    owner.roles.add(roles["Owner"])

    owner_setup_client = APIClient()
    owner_setup_client.force_authenticate(user=owner)
    cash_box = owner_setup_client.post(
        "/api/cash-boxes/", {"legal_entity": str(entity.id), "name": "Cash box"}, format="json"
    )
    assert cash_box.status_code == 201, cash_box.data
    revenue = Account.objects.filter(tenant=tenant, code="4100").first()
    tax_code = TaxCode.objects.get(tenant=tenant, code="Z")
    funding = owner_setup_client.post(
        "/api/vouchers/",
        {
            "voucher_type": "receipt", "legal_entity": str(entity.id), "date": "2026-01-01",
            "treasury_kind": "cash_box", "treasury_id": cash_box.data["id"], "payee_name": "Funding",
            "lines": [{"line_type": "account", "account": str(revenue.id), "tax_code": str(tax_code.id), "amount_fc": "10000.00"}],
        },
        format="json",
    )
    assert funding.status_code == 201, funding.data
    funded = owner_setup_client.post(f"/api/vouchers/{funding.data['id']}/post/")
    assert funded.status_code == 200, funded.data

    creator_client = APIClient()
    creator_client.force_authenticate(user=creator)
    expense = Account.objects.filter(tenant=tenant, code="5100").first()

    voucher = creator_client.post(
        "/api/vouchers/",
        {
            "voucher_type": "payment", "legal_entity": str(entity.id), "date": "2026-01-01",
            "treasury_kind": "cash_box", "treasury_id": cash_box.data["id"], "payee_name": "Big vendor",
            "lines": [{"line_type": "account", "account": str(expense.id), "tax_code": str(tax_code.id), "amount_fc": "6000.00"}],
        },
        format="json",
    )
    assert voucher.status_code == 201, voucher.data

    posted = creator_client.post(f"/api/vouchers/{voucher.data['id']}/post/")
    assert posted.status_code == 202, posted.data
    assert posted.data["status"] == "pending_approval"

    self_approve = creator_client.post(f"/api/vouchers/{voucher.data['id']}/approve/")
    assert self_approve.status_code == 403, self_approve.data

    owner_client = APIClient()
    owner_client.force_authenticate(user=owner)
    inbox = owner_client.get("/api/approvals/pending/")
    assert inbox.status_code == 200
    assert len(inbox.data) == 1
    assert inbox.data[0]["doc_type"] == "voucher_payment"
    assert inbox.data[0]["id"] == voucher.data["id"]

    approved = owner_client.post(f"/api/vouchers/{voucher.data['id']}/approve/")
    assert approved.status_code == 200, approved.data
    assert approved.data["status"] == "posted"

    empty_inbox = owner_client.get("/api/approvals/pending/")
    assert empty_inbox.data == []
