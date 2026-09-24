"""Sprint 6.8 (decision 17): send_pending_approvals_digest — one
combined email per eligible approver listing every pending document;
skips a user with notify_approvals_email=False or no email at all.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.core import mail

from apps.access.models import Role
from apps.access.services import seed_default_roles
from apps.accounting.models import Account
from apps.accounting.services import create_manual_journal_entry, submit_journal_entry_for_approval
from apps.approvals.models import ApprovalRule
from apps.approvals.tasks import send_pending_approvals_digest
from apps.organization.models import LegalEntity

from .factories import UserFactory


def _roles(tenant):
    # user_a (conftest.py) already seeds roles for tenant_a — calling
    # seed_default_roles again here would duplicate the system rows and
    # violate unique_role_name_per_tenant.
    existing = {r.name: r for r in Role.objects.filter(tenant=tenant, is_system=True)}
    return existing or seed_default_roles(tenant)


def _leaf_pair(tenant):
    cash = Account.objects.get(tenant=tenant, system_key="CASH")
    sales = Account.objects.get(tenant=tenant, system_key="SALES")
    return cash, sales


def _submit_entry(tenant, creator, entity, day):
    cash, sales = _leaf_pair(tenant)
    entry = create_manual_journal_entry(
        tenant=tenant, user=creator, legal_entity=entity, date=date(2026, 1, day),
        line_specs=[
            {"account": cash, "debit_fc": Decimal("10.00"), "credit_fc": Decimal("0")},
            {"account": sales, "debit_fc": Decimal("0"), "credit_fc": Decimal("10.00")},
        ],
        currency="SAR", exchange_rate=Decimal("1"),
    )
    submit_journal_entry_for_approval(entry, creator)
    return entry


@pytest.mark.django_db
def test_digest_combines_documents_and_skips_ineligible_users(tenant_a, user_a):
    roles = _roles(tenant_a)
    ApprovalRule.objects.create(
        tenant=tenant_a, doc_type=ApprovalRule.DocType.JOURNAL_ENTRY, min_amount=0, required_role=roles["Owner"]
    )
    user_a.email = "owner@digest.test"
    user_a.notify_approvals_email = True
    user_a.save()

    no_email_user = UserFactory(tenant=tenant_a, email="", notify_approvals_email=True)
    no_email_user.roles.add(roles["Owner"])
    disabled_user = UserFactory(tenant=tenant_a, email="disabled@digest.test", notify_approvals_email=False)
    disabled_user.roles.add(roles["Owner"])

    entity = LegalEntity.objects.get(tenant=tenant_a, entity_type=LegalEntity.Type.BRANCH)
    creator = UserFactory(tenant=tenant_a, email="creator@digest.test")
    for day in (1, 2, 3):
        _submit_entry(tenant_a, creator, entity, day)

    mail.outbox.clear()
    sent = send_pending_approvals_digest()

    assert sent == 1
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == ["owner@digest.test"]
    assert "3" in message.subject
    assert message.body.count("قيد يدوي") == 3


@pytest.mark.django_db
def test_digest_sends_nothing_when_no_documents_are_pending(tenant_a, user_a):
    user_a.email = "owner@digest-empty.test"
    user_a.notify_approvals_email = True
    user_a.save()

    mail.outbox.clear()
    sent = send_pending_approvals_digest()

    assert sent == 0
    assert len(mail.outbox) == 0
