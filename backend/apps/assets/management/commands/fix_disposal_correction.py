"""Sprint 6.5.18: dispose_asset()'s accum_share/gain_loss formula was
wrong for any *cumulative* (second-or-later) disposal of the same
asset — see apps.assets.disposal.dispose_asset's own docstring/comment
for the root cause and the fix. This never touches an already-POSTED
disposal's own JournalEntry (§11: no reversal, no edit) — it posts one
new, real, auditable correcting entry that brings the two affected
system accounts (ACCUM_DEPRECIATION, DISPOSAL_GAIN_LOSS) back to what
they should have read all along, for one specific asset whose disposal
history was affected.

Never raw SQL: an ordinary JournalEntry, numbered and posted through
the same code every other document uses. Idempotent — running it twice
for the same asset is a safe no-op the second time (detected via the
correcting entry's own produced_by/object_id marker — Sprint 7.2.7,
§8.7 site 5 of 7).
"""

from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone


class Command(BaseCommand):
    help = (
        "Posts one correcting JournalEntry for an asset whose cumulative-disposal "
        "accum_share/gain_loss were computed by the pre-6.5.18 buggy formula."
    )

    def add_arguments(self, parser):
        parser.add_argument("--tenant", required=True, help="Tenant subdomain")
        parser.add_argument("--asset", required=True, help="Asset code (Asset.code)")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Compute and print the correction without posting anything.",
        )

    def handle(self, *args, **options):
        from apps.accounting.models import JournalEntry, JournalLine
        from apps.accounting.services import get_system_account
        from apps.assets.models import Asset, AssetDisposal
        from apps.numbering.services import next_document_number
        from apps.tenants.models import Tenant

        subdomain = options["tenant"]
        asset_code = options["asset"]
        dry_run = options["dry_run"]

        try:
            tenant = Tenant.objects.get(subdomain=subdomain)
        except Tenant.DoesNotExist as exc:
            raise CommandError(f"No tenant with subdomain={subdomain!r}") from exc
        try:
            asset = Asset.objects.get(tenant=tenant, code=asset_code)
        except Asset.DoesNotExist as exc:
            raise CommandError(f"No asset with code={asset_code!r} on tenant {subdomain!r}") from exc

        disposals = list(AssetDisposal.objects.filter(asset=asset).order_by("created_at"))
        if not disposals:
            self.stdout.write(self.style.WARNING(f"Asset {asset_code} has no disposals — nothing to check."))
            return

        # Sprint 7.2.7 (§8.7, site 5 of 7 — the one writer): checks
        # produced_by now, not source_type — this command is the first
        # thing that would collide with the §8.7 freeze if it ever ran
        # after produced_by existed but before this site converted.
        already_corrected = JournalEntry.objects.filter(
            tenant=tenant, produced_by="asset_disposal_correction", object_id=asset.id
        ).exists()
        if already_corrected:
            self.stdout.write(self.style.WARNING(f"Asset {asset_code} was already corrected — nothing to do."))
            return

        first = disposals[0]
        if first.fraction == 0:
            raise CommandError(f"Asset {asset_code}'s first disposal has a zero fraction — cannot reconstruct.")
        # The FIRST disposal in the sequence was always computed
        # correctly (disposed_fraction was 0 beforehand, so the old and
        # new formulas agree) — reconstruct the asset's own total
        # accumulated depreciation, as of right before any disposal,
        # from it.
        original_total_accum = (first.accum_share / first.fraction)

        total_accum_diff = Decimal("0")
        total_gain_loss_diff = Decimal("0")
        rows = []
        for disposal in disposals:
            correct_accum_share = (original_total_accum * disposal.fraction).quantize(Decimal("0.01"))
            correct_gain_loss = disposal.proceeds_base - (disposal.cost_share - correct_accum_share)
            accum_diff = disposal.accum_share - correct_accum_share
            gain_loss_diff = disposal.gain_loss - correct_gain_loss
            total_accum_diff += accum_diff
            total_gain_loss_diff += gain_loss_diff
            rows.append(
                {
                    "disposal_id": str(disposal.id), "fraction": str(disposal.fraction),
                    "stored_accum_share": str(disposal.accum_share), "correct_accum_share": str(correct_accum_share),
                    "stored_gain_loss": str(disposal.gain_loss), "correct_gain_loss": str(correct_gain_loss),
                }
            )

        self.stdout.write(f"Asset {asset_code} ({tenant.subdomain}) — {len(disposals)} disposal(s):")
        for row in rows:
            self.stdout.write(f"  {row}")
        self.stdout.write(f"total accum_share over-posted: {total_accum_diff}")
        self.stdout.write(f"total gain_loss over-posted: {total_gain_loss_diff}")

        if total_accum_diff == 0:
            self.stdout.write(self.style.SUCCESS(f"Asset {asset_code}: no correction needed."))
            return

        if dry_run:
            self.stdout.write(self.style.WARNING("--dry-run: no entry posted."))
            return

        with transaction.atomic():
            from django.contrib.contenttypes.models import ContentType

            from apps.accounting.periods import assert_open_period

            accum_account = get_system_account(tenant, "ACCUM_DEPRECIATION")
            gain_loss_account = get_system_account(tenant, "DISPOSAL_GAIN_LOSS")
            today = timezone.localdate()
            # Sprint 7.0 (6.6.10, item 0-bis): dated today, same as
            # reverse_journal_entry/void_invoice_journal_entry's own
            # correcting entries — no reason this one-off script should
            # be the one place that can post into a closed period.
            assert_open_period(tenant, today)

            entry = JournalEntry.objects.create(
                tenant=tenant, legal_entity=asset.legal_entity, date=today,
                memo=f"تصحيح خطأ محرك الاستبعاد 6.5.18 — الأصل {asset.code} — {asset.name}",
                number=next_document_number(tenant, "journal_entry", asset.legal_entity, today),
                status=JournalEntry.Status.POSTED,
                currency=asset.legal_entity.base_currency, exchange_rate=Decimal("1"),
                # source_type/source_id: frozen, kept for the historical
                # trail (never delete a column) — produced_by/content_type/
                # object_id are the live mechanism going forward.
                source_type="asset_disposal_correction", source_id=asset.id,
                produced_by="asset_disposal_correction",
                content_type=ContentType.objects.get_for_model(Asset), object_id=asset.id,
            )
            # total_accum_diff > 0 means ACCUM_DEPRECIATION was
            # over-debited (its own real, historical entries debited it
            # too much) — credit it back down by the excess, and debit
            # DISPOSAL_GAIN_LOSS by the same amount (its own diff
            # mirrors this exactly by construction: gain_loss =
            # proceeds - (cost_share - accum_share), and cost_share/
            # proceeds are both untouched by this bug). A negative
            # diff (the opposite direction, from some other asset's
            # differently-shaped history) gets the mirrored postings —
            # never assume the sign.
            amount = abs(total_accum_diff)
            if total_accum_diff > 0:
                accum_line = JournalLine(
                    entry=entry, account=accum_account, cost_center=asset.cost_center,
                    credit_fc=amount, credit=amount,
                )
                gain_loss_line = JournalLine(
                    entry=entry, account=gain_loss_account, cost_center=asset.cost_center,
                    debit_fc=amount, debit=amount,
                )
            else:
                accum_line = JournalLine(
                    entry=entry, account=accum_account, cost_center=asset.cost_center,
                    debit_fc=amount, debit=amount,
                )
                gain_loss_line = JournalLine(
                    entry=entry, account=gain_loss_account, cost_center=asset.cost_center,
                    credit_fc=amount, credit=amount,
                )
            JournalLine.objects.bulk_create([accum_line, gain_loss_line])

        direction = "credit ACCUM_DEPRECIATION / debit DISPOSAL_GAIN_LOSS" if total_accum_diff > 0 else \
            "debit ACCUM_DEPRECIATION / credit DISPOSAL_GAIN_LOSS"
        self.stdout.write(
            self.style.SUCCESS(
                f"Posted correction JournalEntry {entry.number} (id={entry.id}) for asset {asset_code}: "
                f"{direction} {amount}."
            )
        )
