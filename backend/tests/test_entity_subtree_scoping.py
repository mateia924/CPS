"""Sprint 6.6.7 (docs/prompts/sprint-6.6.md §2 block 6.6.7 + §6.4):
ledger/statement/treasury-movements/close-checklist all scope to a
legal entity's own sub-tree (company -> its branches), same principle
the four reports already use (`apps.reports.services.
_entities_in_scope`) — a company-level read is the sum of its
branches' own lines plus its own direct ones. Also covers the §6.4
performance-debt rewrite: `ledger_lines`'s running balance is now a
SQL window function (not a Python accumulation loop), and
`period_checklist`'s `_posted_documents_without_attachment` batches
its attachment lookups instead of one `.exists()` per document — this
file asserts the RESULTS are unchanged, not the implementation.
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.accounting.models import Account
from apps.accounting.period_close import period_checklist
from apps.accounting.services import (
    create_manual_journal_entry,
    ledger_lines,
    post_journal_entry,
    submit_journal_entry_for_approval,
)
from apps.organization.models import LegalEntity

from .factories import LegalEntityFactory


def _acc(tenant, code):
    return Account.objects.get(tenant=tenant, code=code)


def _post_je(tenant, user, legal_entity, on_date, debit_code, credit_code, amount):
    entry = create_manual_journal_entry(
        tenant=tenant, user=user, legal_entity=legal_entity, date=on_date,
        line_specs=[
            {"account": _acc(tenant, debit_code), "debit_fc": Decimal(amount), "credit_fc": Decimal("0")},
            {"account": _acc(tenant, credit_code), "debit_fc": Decimal("0"), "credit_fc": Decimal(amount)},
        ],
        currency="SAR", exchange_rate=Decimal("1"),
    )
    submit_journal_entry_for_approval(entry, user)
    post_journal_entry(entry, user)
    return entry


@pytest.fixture
def two_branch_setup(tenant_a, user_a):
    company = LegalEntity.objects.get(tenant=tenant_a, entity_type=LegalEntity.Type.COMPANY)
    branch_1 = LegalEntity.objects.get(tenant=tenant_a, entity_type=LegalEntity.Type.BRANCH)
    branch_2 = LegalEntityFactory(tenant=tenant_a, entity_type=LegalEntity.Type.BRANCH, parent=company)

    _post_je(tenant_a, user_a, company, date(2026, 3, 1), "1900", "3100", "100.00")
    _post_je(tenant_a, user_a, branch_1, date(2026, 3, 2), "1900", "3100", "200.00")
    _post_je(tenant_a, user_a, branch_2, date(2026, 3, 3), "1900", "3100", "300.00")
    return company, branch_1, branch_2


@pytest.mark.django_db
def test_ledger_lines_company_scope_sums_both_branches_and_its_own_documents(tenant_a, two_branch_setup):
    company, branch_1, branch_2 = two_branch_setup
    account = _acc(tenant_a, "1900")

    company_wide = ledger_lines(tenant_a, account, legal_entity=company, include_children=True)
    assert company_wide["closing_balance"] == Decimal("600.00")
    assert len(company_wide["lines"]) == 3

    company_only = ledger_lines(tenant_a, account, legal_entity=company, include_children=False)
    assert company_only["closing_balance"] == Decimal("100.00")
    assert len(company_only["lines"]) == 1

    one_branch_only = ledger_lines(tenant_a, account, legal_entity=branch_1, include_children=False)
    assert one_branch_only["closing_balance"] == Decimal("200.00")

    tenant_wide = ledger_lines(tenant_a, account)
    assert tenant_wide["closing_balance"] == Decimal("600.00")


@pytest.mark.django_db
def test_ledger_lines_api_view_wires_include_children(tenant_a, client_a, two_branch_setup):
    company, _branch_1, _branch_2 = two_branch_setup
    account = _acc(tenant_a, "1900")

    resp = client_a.get(f"/api/accounts/{account.id}/ledger/?legal_entity={company.id}&include_children=true")
    assert Decimal(resp.data["closing_balance"]) == Decimal("600.00")

    resp = client_a.get(f"/api/accounts/{account.id}/ledger/?legal_entity={company.id}&include_children=false")
    assert Decimal(resp.data["closing_balance"]) == Decimal("100.00")


@pytest.mark.django_db
def test_period_checklist_entity_scope_narrows_unposted_documents(tenant_a, user_a, two_branch_setup):
    from apps.accounting.models import FiscalPeriod
    from apps.accounting.services import create_manual_journal_entry as create_draft

    company, branch_1, _branch_2 = two_branch_setup
    period = FiscalPeriod.objects.get(
        fiscal_year__tenant=tenant_a, start_date__lte=date(2026, 3, 5), end_date__gte=date(2026, 3, 5)
    )

    # An unposted (DRAFT) entry on branch_1 only — should BLOCK the
    # branch-scoped checklist but not a sibling branch's own scope.
    create_draft(
        tenant=tenant_a, user=user_a, legal_entity=branch_1, date=date(2026, 3, 5),
        line_specs=[
            {"account": _acc(tenant_a, "1900"), "debit_fc": Decimal("50.00"), "credit_fc": Decimal("0")},
            {"account": _acc(tenant_a, "3100"), "debit_fc": Decimal("0"), "credit_fc": Decimal("50.00")},
        ],
        currency="SAR", exchange_rate=Decimal("1"),
    )

    branch_1_items = period_checklist(period, legal_entity=branch_1, include_children=False)
    assert any(item["code"] == "unposted_documents" for item in branch_1_items)

    company_only_items = period_checklist(period, legal_entity=company, include_children=False)
    assert not any(item["code"] == "unposted_documents" for item in company_only_items)

    company_wide_items = period_checklist(period, legal_entity=company, include_children=True)
    assert any(item["code"] == "unposted_documents" for item in company_wide_items)

    tenant_wide_items = period_checklist(period)
    assert any(item["code"] == "unposted_documents" for item in tenant_wide_items)
