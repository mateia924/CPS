"""Sprint 5.7 (docs/CFO_REVIEW_1.md §3 C1): Postgres-level protection
for a POSTED/REVERSED JournalEntry — a real trigger (apps/accounting/
migrations/0019_posted_entry_protection_triggers.py), not just a
Django-level check, since the application code has no UPDATE/DELETE
path to a JournalEntry/JournalLine at all (JournalEntryViewSet only
exposes list/retrieve/create + actions) — this proves the DB itself
refuses it too, for any write that isn't going through this app
(raw SQL, Django admin, a future bug).
"""

from datetime import date
from decimal import Decimal

import pytest
from django.db import DatabaseError, transaction

from apps.access.services import seed_default_roles
from apps.accounting.models import Account, JournalEntry, JournalLine
from apps.accounting.periods import seed_fiscal_year_for_tenant
from apps.accounting.services import (
    approve_journal_entry,
    create_manual_journal_entry,
    post_journal_entry,
    reverse_journal_entry,
    seed_chart_of_accounts,
    seed_tax_codes_for_country,
    submit_journal_entry_for_approval,
)

from .factories import LegalEntityFactory, TenantFactory, UserFactory

# A raw PL/pgSQL RAISE EXCEPTION (no specific SQLSTATE assigned) comes
# back as psycopg's generic ProgrammingError, wrapped by Django as
# DatabaseError — not IntegrityError (that's reserved for actual
# constraint-violation SQLSTATEs). DatabaseError is the right, broad
# assertion below: the behavioral guarantee under test is "the write
# is refused," not which DB-error subclass Postgres happens to pick.


def _posted_entry(tenant, entity, creator, approver):
    cash = Account.objects.get(tenant=tenant, system_key="CASH")
    sales = Account.objects.get(tenant=tenant, system_key="SALES")
    entry = create_manual_journal_entry(
        tenant=tenant, user=creator, legal_entity=entity, date=date(2026, 1, 1),
        line_specs=[
            {"account": cash, "debit_fc": Decimal("40.00"), "credit_fc": Decimal("0")},
            {"account": sales, "debit_fc": Decimal("0"), "credit_fc": Decimal("40.00")},
        ],
        currency="SAR", exchange_rate=Decimal("1"),
    )
    submit_journal_entry_for_approval(entry, creator)
    approve_journal_entry(entry, approver)
    post_journal_entry(entry, approver)
    entry.refresh_from_db()
    return entry


@pytest.fixture
def posted_setup(db):
    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    seed_tax_codes_for_country(tenant, "SA")
    seed_fiscal_year_for_tenant(tenant, start_date=date(2026, 1, 1))
    entity = LegalEntityFactory(tenant=tenant)
    roles = seed_default_roles(tenant)
    creator = UserFactory(tenant=tenant, email="creator@db-trigger.test")
    creator.roles.add(roles["Accountant"])
    approver = UserFactory(tenant=tenant, email="approver@db-trigger.test")
    approver.roles.add(roles["Owner"])
    from apps.approvals.models import ApprovalRule

    ApprovalRule.objects.create(
        tenant=tenant, doc_type=ApprovalRule.DocType.JOURNAL_ENTRY, min_amount=0, required_role=roles["Owner"],
    )
    entry = _posted_entry(tenant, entity, creator, approver)
    return tenant, entity, entry


@pytest.mark.django_db(transaction=True)
def test_direct_update_of_a_posted_journal_line_is_rejected_by_the_database(posted_setup):
    tenant, entity, entry = posted_setup
    line = entry.lines.first()
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            JournalLine.objects.filter(pk=line.pk).update(debit=Decimal("999.00"))


@pytest.mark.django_db(transaction=True)
def test_direct_delete_of_a_posted_journal_line_is_rejected_by_the_database(posted_setup):
    tenant, entity, entry = posted_setup
    line = entry.lines.first()
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            JournalLine.objects.filter(pk=line.pk).delete()


@pytest.mark.django_db(transaction=True)
def test_direct_update_of_a_posted_journal_entry_header_is_rejected(posted_setup):
    tenant, entity, entry = posted_setup
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            JournalEntry.objects.filter(pk=entry.pk).update(memo="tampered")


@pytest.mark.django_db(transaction=True)
def test_direct_delete_of_a_posted_journal_entry_is_rejected(posted_setup):
    tenant, entity, entry = posted_setup
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            JournalEntry.objects.filter(pk=entry.pk).delete()


@pytest.mark.django_db(transaction=True)
def test_the_one_allowed_transition_posted_to_reversed_still_works_via_the_orm(posted_setup):
    """Confirms the trigger's exception list isn't overbroad — the
    application's own reverse path (which sets status+reversed_at only)
    must keep working exactly as before."""
    tenant, entity, entry = posted_setup
    from apps.accounts.models import User

    approver = User.objects.get(tenant=tenant, email="approver@db-trigger.test")
    reversal = reverse_journal_entry(entry, approver, "trigger test reversal")
    assert reversal.status == "posted"
    entry.refresh_from_db()
    assert entry.status == "reversed"
    assert entry.reversed_at is not None


@pytest.mark.django_db(transaction=True)
def test_bank_reconciliation_fields_on_a_posted_line_remain_editable(posted_setup):
    """The trigger's one carve-out on JournalLine — same three columns
    the 5.5 reconciliation engine (not built yet) will need to set."""
    tenant, entity, entry = posted_setup
    line = entry.lines.first()
    from django.utils import timezone

    with transaction.atomic():
        JournalLine.objects.filter(pk=line.pk).update(reconciled_at=timezone.now())
    line.refresh_from_db()
    assert line.reconciled_at is not None


@pytest.mark.django_db(transaction=True)
def test_manually_inserted_unbalanced_lines_fail_at_commit_not_per_row(db):
    """CFO_REVIEW_1 C1's second half — the deferred constraint trigger.
    Two lines inserted in the same transaction that don't balance must
    fail when the transaction commits, proving the check really is
    deferred to commit (not per-row, which would make the first
    INSERT — necessarily "unbalanced" on its own — fail immediately)."""
    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    seed_fiscal_year_for_tenant(tenant, start_date=date(2026, 1, 1))
    entity = LegalEntityFactory(tenant=tenant)
    cash = Account.objects.get(tenant=tenant, system_key="CASH")
    sales = Account.objects.get(tenant=tenant, system_key="SALES")

    with pytest.raises(DatabaseError):
        with transaction.atomic():
            entry = JournalEntry.objects.create(
                tenant=tenant, legal_entity=entity, date=date(2026, 1, 1), status="draft",
                currency="SAR", exchange_rate=Decimal("1"), produced_by=JournalEntry.ProducedBy.MANUAL,
            )
            # Both inserts succeed individually (the trigger only fires
            # at commit) — the mismatch (40 debit vs 30 credit) is only
            # caught when this outer `with` block commits.
            JournalLine.objects.create(
                entry=entry, account=cash, debit=Decimal("40.00"), credit=Decimal("0"),
                currency="SAR", exchange_rate=Decimal("1"),
            )
            JournalLine.objects.create(
                entry=entry, account=sales, debit=Decimal("0"), credit=Decimal("30.00"),
                currency="SAR", exchange_rate=Decimal("1"),
            )

    # The failed transaction rolled back entirely — nothing persisted.
    assert not JournalEntry.objects.filter(tenant=tenant, legal_entity=entity).exists()
