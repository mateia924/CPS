"""Sprint 7.0.3: three named, single-definition functions replace the
three subtly different ad-hoc queries that got hand-written (and twice
got wrong on the first try) during the 7.0.2 incident response —
unreversed_posted_entries, debt_entries, gross_trial_balance. One test
proves all three give different, correct answers on the same fixture:
one genuinely-unresolved forward entry, plus a second forward entry
that was cleanly reversed (its own reversal still sitting at POSTED).
"""

from decimal import Decimal

import pytest

from apps.accounting.models import Account, JournalEntry, JournalLine
from apps.accounting.services import (
    debt_entries,
    gross_trial_balance,
    seed_chart_of_accounts,
    unreversed_posted_entries,
)

from .factories import LegalEntityFactory, TenantFactory


@pytest.mark.django_db
def test_the_three_functions_give_three_different_correct_answers():
    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    entity = LegalEntityFactory(tenant=tenant)
    revenue = Account.objects.get(tenant=tenant, system_key="SALES")
    cash = Account.objects.get(tenant=tenant, system_key="CASH")

    # Genuinely unresolved debt: posted, never reversed. Balanced
    # (debit on cash, credit on revenue) to satisfy the DB's own
    # check_journal_entry_balanced() trigger — unrelated to what this
    # test is proving, but required for any entry to commit at all.
    debt = JournalEntry.objects.create(
        tenant=tenant, legal_entity=entity, date="2026-01-01",
        number="JV-DEBT", status=JournalEntry.Status.POSTED,
        produced_by=JournalEntry.ProducedBy.MANUAL,
    )
    JournalLine.objects.create(entry=debt, account=cash, debit=Decimal("100.00"))
    JournalLine.objects.create(entry=debt, account=revenue, credit=Decimal("100.00"))

    # Cleanly closed pair: the original flips to REVERSED, its reversal
    # is a brand new entry that stays POSTED — not debt, but still real
    # historical activity for the gross total.
    original = JournalEntry.objects.create(
        tenant=tenant, legal_entity=entity, date="2026-01-02",
        number="JV-ORIGINAL", status=JournalEntry.Status.REVERSED,
        produced_by=JournalEntry.ProducedBy.MANUAL,
    )
    JournalLine.objects.create(entry=original, account=cash, debit=Decimal("50.00"))
    JournalLine.objects.create(entry=original, account=revenue, credit=Decimal("50.00"))
    reversal = JournalEntry.objects.create(
        tenant=tenant, legal_entity=entity, date="2026-01-03",
        number="JV-REVERSAL", status=JournalEntry.Status.POSTED, reverses=original,
        produced_by=JournalEntry.ProducedBy.MANUAL,
    )
    JournalLine.objects.create(entry=reversal, account=revenue, debit=Decimal("50.00"))
    JournalLine.objects.create(entry=reversal, account=cash, credit=Decimal("50.00"))

    # unreversed_posted_entries: everything currently sitting at POSTED
    # — the debt entry AND the reversal entry (reversals are POSTED too).
    assert set(unreversed_posted_entries(tenant)) == {debt, reversal}

    # debt_entries: only the genuinely unresolved one — the reversal is
    # excluded because it is itself a reversal (reverses is not null).
    assert list(debt_entries(tenant)) == [debt]

    # gross_trial_balance: every line on POSTED or REVERSED entries,
    # including the now-REVERSED original — 100 + 50 + 50 = 200.00.
    assert gross_trial_balance(tenant) == Decimal("200.00")
