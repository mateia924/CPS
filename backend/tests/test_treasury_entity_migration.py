"""Sprint 6.5.15 (UAT item 5): a simplified-mode tenant's own treasury
accounts must end up on the same entity its vouchers actually post on
— see docs/prompts/sprint-6.5.md §6.5.15 for the live "fatma" evidence
(a cash box left on the company entity while every voucher posts on
the branch). Real HTTP API + real Postgres throughout (§11).
"""

from datetime import date as date_
from decimal import Decimal

import pytest

from apps.organization.models import LegalEntity
from apps.treasury.models import CashBox


def _branch(tenant):
    return LegalEntity.objects.get(tenant=tenant, entity_type=LegalEntity.Type.BRANCH)


def _company(tenant):
    return LegalEntity.objects.get(tenant=tenant, entity_type=LegalEntity.Type.COMPANY)


@pytest.mark.django_db
def test_has_movements_is_false_for_a_fresh_treasury_account(tenant_a, client_a):
    response = client_a.post(
        "/api/cash-boxes/", {"legal_entity": str(_branch(tenant_a).id), "name": "Box", "currency": "SAR"}, format="json"
    )
    assert response.status_code == 201, response.data
    assert response.data["has_movements"] is False


@pytest.mark.django_db
def test_has_movements_is_true_once_a_voucher_posts_against_it(tenant_a, client_a, user_a):
    from apps.accounting.models import Account
    from apps.accounting.services import (
        create_manual_journal_entry,
        post_journal_entry,
        submit_journal_entry_for_approval,
    )

    entity = _branch(tenant_a)
    cash_box = CashBox.objects.create(tenant=tenant_a, legal_entity=entity, name="Box", currency="SAR")

    revenue = Account.objects.filter(tenant=tenant_a, code="4100").first()
    entry = create_manual_journal_entry(
        tenant=tenant_a, user=user_a, legal_entity=entity, date=date_(2026, 3, 1),
        line_specs=[
            {"account": Account.objects.get(tenant=tenant_a, code="1900"), "debit_fc": Decimal("10.00"), "credit_fc": Decimal("0")},
            {"account": revenue, "debit_fc": Decimal("0"), "credit_fc": Decimal("10.00")},
        ],
        currency="SAR", exchange_rate=Decimal("1"),
    )
    submit_journal_entry_for_approval(entry, user_a)
    post_journal_entry(entry, user_a)

    # A manual JV never touches has_movements — only Voucher does (the
    # field's own contract). Fund the box for real via a voucher.
    response = client_a.post(
        "/api/vouchers/",
        {
            "voucher_type": "receipt", "legal_entity": str(entity.id), "date": "2026-03-02",
            "treasury_kind": "cash_box", "treasury_id": str(cash_box.id), "payee_name": "Funding",
            "lines": [
                {
                    "line_type": "account", "account": str(revenue.id),
                    "tax_code": str(_tax_code_z(tenant_a).id), "amount_fc": "50.00",
                }
            ],
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    posted = client_a.post(f"/api/vouchers/{response.data['id']}/post/")
    assert posted.status_code == 200, posted.data

    detail = client_a.get(f"/api/cash-boxes/{cash_box.id}/")
    assert detail.data["has_movements"] is True


def _tax_code_z(tenant):
    from apps.accounting.models import TaxCode

    return TaxCode.objects.get(tenant=tenant, code="Z")


@pytest.mark.django_db
def test_migration_moves_untouched_treasury_but_leaves_ones_with_movements(tenant_a, client_a):
    """Direct test of the migration's own move function (same pattern
    as tests/test_reports.py's normal_balance backfill test) — proves
    the exact decision: untouched moves to the branch, anything with a
    real voucher against it never moves."""
    import importlib

    from django.apps import apps as django_apps

    company, branch = _company(tenant_a), _branch(tenant_a)
    untouched_box = CashBox.objects.create(tenant=tenant_a, legal_entity=company, name="Untouched", currency="SAR")
    touched_box = CashBox.objects.create(tenant=tenant_a, legal_entity=company, name="Touched", currency="SAR")

    from apps.accounting.models import Account

    revenue = Account.objects.filter(tenant=tenant_a, code="4100").first()
    response = client_a.post(
        "/api/vouchers/",
        {
            "voucher_type": "receipt", "legal_entity": str(company.id), "date": "2026-03-02",
            "treasury_kind": "cash_box", "treasury_id": str(touched_box.id), "payee_name": "Funding",
            "lines": [
                {
                    "line_type": "account", "account": str(revenue.id),
                    "tax_code": str(_tax_code_z(tenant_a).id), "amount_fc": "50.00",
                }
            ],
        },
        format="json",
    )
    assert response.status_code == 201, response.data

    migration = importlib.import_module("apps.treasury.migrations.0008_move_untouched_treasury_to_branch")
    migration.move_untouched_treasury_to_branch(django_apps, None)

    untouched_box.refresh_from_db()
    touched_box.refresh_from_db()
    assert untouched_box.legal_entity_id == branch.id
    assert touched_box.legal_entity_id == company.id


@pytest.mark.django_db
def test_tenant_isolation(tenant_a, client_a, tenant_b, client_b):
    box = CashBox.objects.create(tenant=tenant_a, legal_entity=_branch(tenant_a), name="Box", currency="SAR")
    response = client_b.get(f"/api/cash-boxes/{box.id}/")
    assert response.status_code == 404
