"""Sprint 6.5.18: `fix_disposal_correction` posts one real, auditable
correcting JournalEntry for an asset whose disposal history was
computed by the pre-6.5.18 buggy accum_share/gain_loss formula (see
apps.assets.disposal.dispose_asset's own fix). Never a reversal of any
posted disposal entry, never raw SQL — a normal, numbered, POSTED
JournalEntry through the same code every other document uses. Real
Postgres throughout (§11).
"""

from datetime import date
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from apps.accounting.models import Account, JournalEntry
from apps.accounting.services import (
    create_manual_journal_entry,
    post_journal_entry,
    submit_journal_entry_for_approval,
)
from apps.assets.models import Asset, AssetDisposal

from .factories import AssetFactory, LegalEntityFactory


def _entity(tenant):
    return LegalEntityFactory(tenant=tenant)


def _seed_asset_with_buggy_disposal_history(tenant, user, entity):
    """Directly constructs the exact "fatma" shape — two AssetDisposal
    rows where the second's accum_share/gain_loss were computed by the
    pre-fix formula — bypassing dispose_asset() entirely (the live
    code is already fixed, so it can no longer reproduce this by
    itself; this is the same real numbers the live incident had)."""
    asset = AssetFactory(
        tenant=tenant, legal_entity=entity, purchase_date="2026-01-01", purchase_cost="14400.00",
        salvage_value="0", useful_life_months=12, opening_accumulated_depreciation="0.00",
        cost_base="14400.00", salvage_base="0.00", disposed_fraction="1.0000", status=Asset.Status.DISPOSED,
    )
    fixed_assets = Account.objects.get(tenant=tenant, system_key="FIXED_ASSETS")
    accum = Account.objects.get(tenant=tenant, system_key="ACCUM_DEPRECIATION")
    opening_balance = Account.objects.get(tenant=tenant, system_key="OPENING_BALANCE")
    gain_loss = Account.objects.get(tenant=tenant, system_key="DISPOSAL_GAIN_LOSS")
    cash = Account.objects.get(tenant=tenant, system_key="CASH")

    opening = create_manual_journal_entry(
        tenant=tenant, user=user, legal_entity=entity, date=date(2026, 1, 1),
        line_specs=[
            {"account": fixed_assets, "debit_fc": Decimal("14400.00"), "credit_fc": Decimal("0")},
            {"account": accum, "debit_fc": Decimal("0"), "credit_fc": Decimal("1000.00")},
            {"account": opening_balance, "debit_fc": Decimal("0"), "credit_fc": Decimal("13400.00")},
        ],
        currency="SAR", exchange_rate=Decimal("1"), override_reason="رصيد افتتاحي للأصل",
    )
    submit_journal_entry_for_approval(opening, user)
    post_journal_entry(opening, user)

    # Disposal 1 (0.3, 3,000 proceeds) — always correct, even under the
    # old formula (nothing disposed yet beforehand).
    d1 = AssetDisposal.objects.create(
        tenant=tenant, asset=asset, date=date(2026, 9, 26), fraction=Decimal("0.3"),
        proceeds_base=Decimal("3000.00"), cost_share=Decimal("4320.00"), accum_share=Decimal("300.00"),
        gain_loss=Decimal("-1020.00"), created_by=user,
    )
    je1 = create_manual_journal_entry(
        tenant=tenant, user=user, legal_entity=entity, date=d1.date,
        line_specs=[
            {"account": accum, "debit_fc": Decimal("300.00"), "credit_fc": Decimal("0")},
            {"account": fixed_assets, "debit_fc": Decimal("0"), "credit_fc": Decimal("4320.00")},
            {"account": cash, "debit_fc": Decimal("3000.00"), "credit_fc": Decimal("0")},
            {"account": gain_loss, "debit_fc": Decimal("1020.00"), "credit_fc": Decimal("0")},
        ],
        currency="SAR", exchange_rate=Decimal("1"), override_reason="استبعاد جزئي (بيانات اختبار)",
    )
    submit_journal_entry_for_approval(je1, user)
    post_journal_entry(je1, user)
    d1.journal_entry = je1
    d1.save(update_fields=["journal_entry"])

    # Disposal 2 (0.7, 11,000 proceeds) — the buggy formula's real
    # output: accum_share 3,514.00 / gain_loss +4,434.00 (should have
    # been 700.00 / +1,620.00).
    d2 = AssetDisposal.objects.create(
        tenant=tenant, asset=asset, date=date(2026, 9, 30), fraction=Decimal("0.7"),
        proceeds_base=Decimal("11000.00"), cost_share=Decimal("10080.00"), accum_share=Decimal("3514.00"),
        gain_loss=Decimal("4434.00"), created_by=user,
    )
    je2 = create_manual_journal_entry(
        tenant=tenant, user=user, legal_entity=entity, date=d2.date,
        line_specs=[
            {"account": accum, "debit_fc": Decimal("3514.00"), "credit_fc": Decimal("0")},
            {"account": fixed_assets, "debit_fc": Decimal("0"), "credit_fc": Decimal("10080.00")},
            {"account": cash, "debit_fc": Decimal("11000.00"), "credit_fc": Decimal("0")},
            {"account": gain_loss, "debit_fc": Decimal("0"), "credit_fc": Decimal("4434.00")},
        ],
        currency="SAR", exchange_rate=Decimal("1"), override_reason="استبعاد جزئي (بيانات اختبار)",
    )
    submit_journal_entry_for_approval(je2, user)
    post_journal_entry(je2, user)
    d2.journal_entry = je2
    d2.save(update_fields=["journal_entry"])

    return asset


@pytest.mark.django_db
def test_dry_run_reports_correct_diagnosis_without_posting(tenant_a, user_a):
    entity = _entity(tenant_a)
    asset = _seed_asset_with_buggy_disposal_history(tenant_a, user_a, entity)

    out = StringIO()
    call_command("fix_disposal_correction", "--tenant", tenant_a.subdomain, "--asset", asset.code, "--dry-run", stdout=out)
    output = out.getvalue()
    assert "total accum_share over-posted: 2814.00" in output
    assert "no entry posted" in output
    assert not JournalEntry.objects.filter(
        tenant=tenant_a, produced_by=JournalEntry.ProducedBy.ASSET_DISPOSAL_CORRECTION
    ).exists()


@pytest.mark.django_db
def test_posts_a_real_correcting_entry_that_fixes_the_gl_balances(tenant_a, user_a):
    entity = _entity(tenant_a)
    asset = _seed_asset_with_buggy_disposal_history(tenant_a, user_a, entity)

    accum = Account.objects.get(tenant=tenant_a, system_key="ACCUM_DEPRECIATION")
    gain_loss = Account.objects.get(tenant=tenant_a, system_key="DISPOSAL_GAIN_LOSS")

    def _closing(account):
        lines = account.journal_lines.filter(entry__tenant=tenant_a, entry__status="posted")
        return sum((line.debit - line.credit for line in lines), Decimal("0"))

    assert _closing(accum) == Decimal("2814.00")  # the live bug's own real shape

    out = StringIO()
    call_command("fix_disposal_correction", "--tenant", tenant_a.subdomain, "--asset", asset.code, stdout=out)
    output = out.getvalue()
    assert "Posted correction JournalEntry" in output

    correction = JournalEntry.objects.get(
        tenant=tenant_a, produced_by=JournalEntry.ProducedBy.ASSET_DISPOSAL_CORRECTION, object_id=asset.id
    )
    assert correction.status == JournalEntry.Status.POSTED
    assert correction.number

    assert _closing(accum) == Decimal("0.00")
    # gain_loss is credit-normal; net gain should now read 600.00.
    gl_lines = gain_loss.journal_lines.filter(entry__tenant=tenant_a, entry__status="posted")
    net_gain = sum((line.credit - line.debit for line in gl_lines), Decimal("0"))
    assert net_gain == Decimal("600.00")

    # Neither of the two ORIGINAL disposal JournalEntries was touched —
    # a new, third entry was added alongside them, unchanged.
    je1 = asset.disposals.get(fraction=Decimal("0.3")).journal_entry
    je2 = asset.disposals.get(fraction=Decimal("0.7")).journal_entry
    assert {line.credit_fc for line in je1.lines.all()} & {Decimal("4320.00")}
    assert {line.credit_fc for line in je2.lines.all()} & {Decimal("10080.00")}
    assert JournalEntry.objects.filter(tenant=tenant_a, status=JournalEntry.Status.POSTED).count() == 4

    # Idempotent — a second run is a safe no-op.
    out2 = StringIO()
    call_command("fix_disposal_correction", "--tenant", tenant_a.subdomain, "--asset", asset.code, stdout=out2)
    assert "already corrected" in out2.getvalue()
    assert JournalEntry.objects.filter(
        tenant=tenant_a, produced_by=JournalEntry.ProducedBy.ASSET_DISPOSAL_CORRECTION
    ).count() == 1
