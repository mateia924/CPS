"""Sprint 6.5 (block 6.5.4, decision 7): full and partial asset
disposal — cumulative fractions of the *original* asset (Σ ≤ 1), cost
and accumulated-depreciation shares taken at that same fraction, and a
single POSTED JournalEntry at approval time whose gain/loss on
DISPOSAL_GAIN_LOSS is computed, never entered. The remaining share (if
any) is rescheduled the same way an addition recomputes (apps.assets.
depreciation._reschedule_remaining) — but as a mechanical side effect
of the disposal's own already-approved decision, not a second
approval-gated document (decision 11 names exactly three doc types:
starting a schedule, an addition, and a disposal — not a fourth for a
disposal's internal reschedule)."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from apps.accounting.models import JournalEntry, JournalLine, RecurringEntry
from apps.accounting.periods import assert_open_period
from apps.accounting.services import CENTS, get_system_account
from apps.numbering.services import next_document_number
from apps.platform.models import AuditLog
from apps.platform.services import log_action

from .depreciation import (
    _activate_schedule,
    _assign_number_if_missing,
    _reschedule_remaining,
    current_book_value,
)
from .models import Asset, AssetDisposal

DOC_TYPE = "asset_disposal"


@transaction.atomic
def dispose_asset(
    asset, user, date, fraction, proceeds_base=Decimal("0"), proceeds_account=None, proceeds_party=None,
    proceeds_party_role="", reason="", request=None,
):
    """Decision 7. Returns the AssetDisposal row (still DRAFT/PENDING_
    APPROVAL/APPROVED depending on whether a matching rule exists)."""
    if fraction <= 0:
        raise ValidationError(str(_("كسر الاستبعاد يجب أن يكون أكبر من صفر.")))
    if asset.status == Asset.Status.DISPOSED:
        raise ValidationError(str(_("الأصل مُستبعَد بالكامل بالفعل.")))
    total_fraction = asset.disposed_fraction + fraction
    if total_fraction > 1:
        raise ValidationError(str(_("مجموع كسور الاستبعاد يتجاوز أصل الأصل (100%%).")))

    cost_total = asset.cost_base if asset.cost_base is not None else asset.purchase_cost
    book_value = current_book_value(asset)
    accum_total = cost_total - book_value
    cost_share = (cost_total * fraction).quantize(CENTS)
    accum_share = (accum_total * fraction).quantize(CENTS)
    gain_loss = proceeds_base - (cost_share - accum_share)

    resolved_account, resolved_party, resolved_role = None, None, ""
    if proceeds_base > 0:
        # Decision 7: "سطر العائد يُحدَّد بمحلّل «حساب أو طرف+دور» نفسه
        # من 6.3" — proceeds == 0 means "scrapped, no proceeds line at
        # all", so this resolution never even runs.
        from apps.accounting.opening_balances import _resolve_line_account

        resolved_account, resolved_party, resolved_role = _resolve_line_account(
            {"account": proceeds_account, "party": proceeds_party, "party_role": proceeds_party_role}
        )

    disposal = AssetDisposal.objects.create(
        tenant=asset.tenant, asset=asset, date=date, fraction=fraction, proceeds_base=proceeds_base,
        proceeds_account=resolved_account, proceeds_party=resolved_party, proceeds_party_role=resolved_role,
        reason=reason, cost_share=cost_share, accum_share=accum_share, gain_loss=gain_loss, created_by=user,
    )
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER, actor_id=user.id, action="asset_disposal.created",
        target_type="asset", target_id=asset.id, tenant_id=asset.tenant_id,
        after={"fraction": str(fraction), "disposal": str(disposal.id)}, request=request,
    )

    from apps.approvals.services import submit_for_approval

    auto_approved = submit_for_approval(disposal, user, DOC_TYPE, cost_share, request=request)
    if auto_approved:
        _finish_disposal(disposal, user, request=request)
    return disposal


def _post_disposal_entry(disposal, user):
    asset = disposal.asset
    tenant = asset.tenant
    assert_open_period(tenant, disposal.date)

    fixed_assets = get_system_account(tenant, "FIXED_ASSETS")
    accum_account = get_system_account(tenant, "ACCUM_DEPRECIATION")
    gain_loss_account = get_system_account(tenant, "DISPOSAL_GAIN_LOSS")

    journal_entry = JournalEntry.objects.create(
        tenant=tenant, legal_entity=asset.legal_entity, date=disposal.date,
        memo=str(
            _("استبعاد %(percent)s%% من الأصل %(code)s — %(name)s")
            % {"percent": (disposal.fraction * 100).normalize(), "code": asset.code, "name": asset.name}
        ),
        number=next_document_number(tenant, "journal_entry", asset.legal_entity, disposal.date),
        status=JournalEntry.Status.POSTED, created_by=user,
        currency=asset.legal_entity.base_currency, exchange_rate=Decimal("1"),
        source_type="asset_disposal", source_id=disposal.id,
    )
    lines = [
        JournalLine(
            entry=journal_entry, account=accum_account, cost_center=asset.cost_center,
            debit_fc=disposal.accum_share, debit=disposal.accum_share,
        ),
        JournalLine(
            entry=journal_entry, account=fixed_assets, cost_center=asset.cost_center,
            credit_fc=disposal.cost_share, credit=disposal.cost_share,
        ),
    ]
    if disposal.proceeds_base > 0:
        lines.append(
            JournalLine(
                entry=journal_entry, account=disposal.proceeds_account, party=disposal.proceeds_party,
                cost_center=asset.cost_center, debit_fc=disposal.proceeds_base, debit=disposal.proceeds_base,
            )
        )
    if disposal.gain_loss > 0:
        lines.append(
            JournalLine(
                entry=journal_entry, account=gain_loss_account, cost_center=asset.cost_center,
                credit_fc=disposal.gain_loss, credit=disposal.gain_loss,
            )
        )
    elif disposal.gain_loss < 0:
        loss = -disposal.gain_loss
        lines.append(
            JournalLine(
                entry=journal_entry, account=gain_loss_account, cost_center=asset.cost_center,
                debit_fc=loss, debit=loss,
            )
        )
    JournalLine.objects.bulk_create(lines)
    return journal_entry


@transaction.atomic
def _finish_disposal(disposal, user, request=None):
    asset = disposal.asset
    journal_entry = _post_disposal_entry(disposal, user)
    disposal.journal_entry = journal_entry
    disposal.save(update_fields=["journal_entry"])

    new_total_fraction = asset.disposed_fraction + disposal.fraction
    asset.disposed_fraction = new_total_fraction
    old_entry = asset.depreciation_entry

    if new_total_fraction >= 1:
        # Decision 7: full disposal — nothing left to depreciate.
        # cancel_recurring_entry also cancels the disposal month's own
        # DUE installment if it hasn't been generated yet ("لا إهلاك
        # في شهر الاستبعاد إن لم يُولَّد قسطه بعد") — no extra code
        # needed, it cancels every DUE installment unconditionally.
        asset.status = Asset.Status.DISPOSED
        _cancellable = {
            RecurringEntry.Status.DRAFT, RecurringEntry.Status.PENDING_APPROVAL, RecurringEntry.Status.APPROVED,
        }
        if old_entry is not None and old_entry.status in _cancellable:
            from apps.accounting.recurring import cancel_recurring_entry

            cancel_recurring_entry(old_entry, user, request=request)
        asset.depreciation_entry = None
    elif old_entry is not None and old_entry.status == RecurringEntry.Status.APPROVED:
        # Decision 7 + block text "جدول جديد لـ70% صحيح": the remaining
        # share keeps depreciating over what's left — remaining book
        # value (after this disposal) minus the remaining salvage
        # share, over whatever installments were still DUE. This is a
        # mechanical side effect of the disposal's own already-approved
        # decision, so the new entry is activated directly rather than
        # going through its own separate submit_for_approval.
        remaining_book_value = current_book_value(asset) - (disposal.cost_share - disposal.accum_share)
        remaining_salvage = (asset.salvage_base or Decimal("0")) * (Decimal("1") - new_total_fraction)
        new_total = remaining_book_value - remaining_salvage
        new_count = old_entry.installments.filter(status="due").count()

        new_entry = _reschedule_remaining(asset, old_entry, new_total, new_count, disposal.date, user, request=request)
        # _reschedule_remaining just locked old_entry's full generated
        # total into opening_accumulated_depreciation (correct for an
        # addition's own call into it, which never removes a share) —
        # a disposal's own share of that must now come back out, since
        # this disposal's own JournalLine already debited exactly that
        # much out of ACCUM_DEPRECIATION (apps.assets.reconciliation.
        # register_totals's docstring has the full accounting for why).
        asset.opening_accumulated_depreciation -= disposal.accum_share
        asset.depreciation_entry = new_entry

    asset.save(update_fields=["disposed_fraction", "status", "depreciation_entry", "opening_accumulated_depreciation"])

    if new_total_fraction < 1 and asset.depreciation_entry is not None:
        # Decision 7's mechanical side effect, activated directly
        # (never a second submit_for_approval — see the comment
        # above). asset.depreciation_entry must already be saved to
        # point at it first: _activate_schedule looks the owning Asset
        # back up via that FK.
        new_entry = asset.depreciation_entry
        new_entry.description = str(
            _("إهلاك %(code)s — %(name)s (بعد استبعاد جزئي)") % {"code": asset.code, "name": asset.name}
        )
        new_entry.status = RecurringEntry.Status.APPROVED
        new_entry.save(update_fields=["description", "status"])
        _assign_number_if_missing(new_entry)
        _activate_schedule(new_entry)

    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER, actor_id=user.id, action="asset_disposal.finished",
        target_type="asset", target_id=asset.id, tenant_id=asset.tenant_id,
        after={"journal_entry": str(journal_entry.id), "disposed_fraction": str(new_total_fraction)},
        request=request,
    )


@transaction.atomic
def approve_disposal(disposal, user, request=None, emergency_reason=""):
    from apps.approvals.services import approve as approvals_approve

    approvals_approve(disposal, user, DOC_TYPE, disposal.cost_share, request=request, emergency_reason=emergency_reason)
    _finish_disposal(disposal, user, request=request)
    return disposal


def reject_disposal(disposal, user, reason, request=None):
    from apps.approvals.services import reject as approvals_reject

    return approvals_reject(disposal, user, DOC_TYPE, reason, request=request)


def withdraw_disposal(disposal, user, request=None):
    from apps.approvals.services import withdraw as approvals_withdraw

    return approvals_withdraw(disposal, user, DOC_TYPE, request=request)
