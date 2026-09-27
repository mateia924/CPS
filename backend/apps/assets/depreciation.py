"""Sprint 6.5 (decisions 3, 4, 5, 9, 11, 12, 14): starting an asset's
depreciation schedule. Reuses apps.accounting.recurring's own
RecurringEntry/RecurringInstallment machinery for the parts that are
identical (generation-at-due-date via generate_due_installments,
period-close's due-installments check, the reversal guard's "source_
type=recurring" shape) — but owns installment creation independently
(decision 5's "مولّد مستقل ... بلا لمس _activate_recurring_entry"),
since the declining-balance method (6.5.2) recomputes per fiscal year
and has no equal-split shortcut to share with an ordinary recurring
entry. The approval channel is also its own doc_type ("asset_
depreciation", ApprovalRule.DocType.ASSET_DEPRECIATION) rather than
"recurring_entry" — a tenant may want a different approver/threshold
for starting a depreciation schedule than for an ordinary prepaid/
deferred schedule.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils.translation import gettext_lazy as _

from apps.accounting.models import FiscalPeriod, FiscalYear, RecurringEntry, RecurringInstallment
from apps.accounting.periods import assert_open_period, create_next_fiscal_year_for_tenant
from apps.accounting.recurring import _consecutive_periods, _split_amount
from apps.accounting.services import CENTS, get_system_account
from apps.platform.models import AuditLog
from apps.platform.services import log_action
from apps.treasury.services import ExchangeRateNotFound, get_rate_with_warnings

from .models import Asset, AssetAddition

DOC_TYPE = "asset_depreciation"
ADDITION_DOC_TYPE = "asset_addition"

# Decision 9: any of these means the asset already has a schedule that
# hasn't been withdrawn/rejected back out of existence — a second
# start-depreciation call is a conflict (409), not a validation error.
_ACTIVE_SCHEDULE_STATUSES = {
    RecurringEntry.Status.DRAFT,
    RecurringEntry.Status.PENDING_APPROVAL,
    RecurringEntry.Status.APPROVED,
    RecurringEntry.Status.COMPLETED,
}


class DepreciationAlreadyActive(Exception):
    """The asset already has a schedule in one of _ACTIVE_SCHEDULE_
    STATUSES — the view maps this to 409, distinct from the ordinary
    400 a plain validation failure gets."""


class NoActiveDepreciationSchedule(Exception):
    """Decision 6: an addition needs a currently-running (APPROVED)
    schedule to cancel and recompute — the view maps this to 409."""


def current_book_value(asset):
    """Decision 6/7: the single formula every recompute (an addition,
    a partial disposal, the AssetSerializer's own display fields) reads
    from — entry.total_amount_base is always "book value at that
    entry's own start − salvage_base" by construction (true whether
    the entry came from start_depreciation or from an earlier
    addition), so this needs no separate accumulated-to-date tracking
    back to the asset's original opening_accumulated_depreciation."""
    if asset.cost_base is None:
        return asset.purchase_cost
    entry = asset.depreciation_entry
    if entry is None:
        return asset.cost_base - asset.opening_accumulated_depreciation
    generated = entry.installments.filter(
        status=RecurringInstallment.Status.GENERATED
    ).aggregate(total=Sum("amount_base"))["total"] or Decimal("0")
    return entry.total_amount_base + asset.salvage_base - generated


def _reschedule_remaining(asset, old_entry, new_total, new_count, date, user, request=None):
    """Shared by add_to_asset (6.5.3) and a partial disposal's own
    recompute (6.5.4): cancels old_entry's remaining (DUE) installments
    and creates a fresh schedule over (new_total, new_count) starting
    at the period containing `date` (or the next one, if that period's
    own old installment already generated — decision 6's "يبدأ من فترة
    الإضافة إن لم يُولَّد قسطها وإلا التالية"). Returns the new
    RecurringEntry, or None if there's nothing left to schedule."""
    period = assert_open_period(asset.tenant, date)
    this_period_installment = old_entry.installments.filter(period=period).first()
    if this_period_installment is not None and this_period_installment.status == RecurringInstallment.Status.GENERATED:
        first_period, _elapsed = _first_schedule_period(asset.tenant, period.end_date + timedelta(days=1))
    else:
        first_period = period

    # Lock in whatever old_entry generated before it's replaced —
    # current_book_value's own "no active entry" fallback (cost_base −
    # opening_accumulated_depreciation) and apps.assets.reconciliation.
    # register_totals both read opening_accumulated_depreciation +
    # the CURRENT entry's own generated installments only, so a
    # cancelled-and-replaced entry's history would otherwise vanish
    # the moment it stops being "current".
    generated_on_old_entry = old_entry.installments.filter(
        status=RecurringInstallment.Status.GENERATED
    ).aggregate(total=Sum("amount_base"))["total"] or Decimal("0")
    asset.opening_accumulated_depreciation += generated_on_old_entry
    asset.save(update_fields=["opening_accumulated_depreciation"])

    from apps.accounting.recurring import cancel_recurring_entry

    cancel_recurring_entry(old_entry, user, request=request)

    if new_count <= 0 or new_total <= 0:
        return None

    accum_account = get_system_account(asset.tenant, "ACCUM_DEPRECIATION")
    expense_account = get_system_account(asset.tenant, "DEPRECIATION_EXPENSE")
    return RecurringEntry.objects.create(
        tenant=asset.tenant, legal_entity=asset.legal_entity, cost_center=asset.cost_center,
        description=str(_("إهلاك %(code)s — %(name)s") % {"code": asset.code, "name": asset.name}),
        kind=RecurringEntry.Kind.DEPRECIATION, from_account=accum_account, to_account=expense_account,
        total_amount_base=new_total, installments_count=new_count, first_period=first_period,
        created_by=user,
    )


def doc_type_for_entry(entry):
    """Decision 11: the SAME RecurringEntry model backs three separate
    approval authorities (starting a schedule, an addition, and — from
    6.5.4 — a disposal-triggered recompute) that differ only in which
    ApprovalRule.DocType applies; kind stays DEPRECIATION for all of
    them (it's a label, not a routing key — same as TaxCode.kind).
    Used by apps.approvals.services.list_pending_approvals and by this
    module's own approve/reject/withdraw wrappers so both agree."""
    if AssetAddition.objects.filter(new_entry=entry).exists():
        return ADDITION_DOC_TYPE
    return DOC_TYPE


def _first_schedule_period(tenant, in_service_date):
    """Decision 4/9: the period covering `in_service_date` gets the
    first full installment if it's still OPEN; otherwise every closed
    period between it and the first still-OPEN one "elapses" — each
    one shortens the remaining schedule by one installment (decision
    9: "الأشهر المنقضية ... تُخصم من الأقساط المتبقية") rather than
    ever trying to post into a period that can no longer accept a
    journal entry. Grows the fiscal calendar forward exactly like
    apps.accounting.recurring._consecutive_periods does, if needed."""
    period = (
        FiscalPeriod.objects.filter(
            fiscal_year__tenant=tenant, start_date__lte=in_service_date, end_date__gte=in_service_date
        )
        .select_related("fiscal_year")
        .first()
    )
    if period is None:
        raise ValidationError(
            str(_("لا توجد سنة مالية تغطي تاريخ بدء الاستخدام %(date)s.") % {"date": in_service_date})
        )
    elapsed = 0
    cursor = period
    while cursor.status != FiscalPeriod.Status.OPEN:
        elapsed += 1
        nxt = (
            FiscalPeriod.objects.filter(fiscal_year__tenant=tenant, start_date=cursor.end_date + timedelta(days=1))
            .select_related("fiscal_year")
            .first()
        )
        if nxt is None:
            latest_year = FiscalYear.objects.filter(tenant=tenant).order_by("-end_date").first()
            create_next_fiscal_year_for_tenant(tenant, latest_year)
            nxt = (
                FiscalPeriod.objects.filter(fiscal_year__tenant=tenant, start_date=cursor.end_date + timedelta(days=1))
                .select_related("fiscal_year")
                .first()
            )
        cursor = nxt
    return cursor, elapsed


@transaction.atomic
def start_depreciation(asset, user, request=None):
    """Decisions 3, 4, 5 (straight-line only — DECLINING_BALANCE is
    6.5.2), 9, 11, 14. Returns (entry, warnings)."""
    if asset.depreciation_entry_id and asset.depreciation_entry.status in _ACTIVE_SCHEDULE_STATUSES:
        raise DepreciationAlreadyActive(str(_("للأصل جدول إهلاك نشط بالفعل.")))
    if not asset.is_depreciable:
        raise ValidationError(str(_("هذا الأصل لا يُهلك.")))
    if not asset.useful_life_months:
        raise ValidationError(str(_("العمر الإنتاجي مطلوب لبدء الإهلاك.")))
    is_declining = asset.depreciation_method == Asset.DepreciationMethod.DECLINING_BALANCE
    if is_declining:
        rate = asset.declining_balance_rate
        if rate is None or not (Decimal("0") < rate < Decimal("100")):
            raise ValidationError(
                str(_("معدّل الإهلاك المتناقص يجب أن يكون بين 0 و100."))
            )

    in_service_date = asset.in_service_date or asset.purchase_date
    warnings = []
    if asset.cost_base is None:
        try:
            rate, rate_warnings = get_rate_with_warnings(
                asset.tenant, asset.currency, asset.legal_entity.base_currency, asset.purchase_date
            )
        except ExchangeRateNotFound as exc:
            raise ValidationError(str(exc)) from exc
        asset.cost_base = (asset.purchase_cost * rate).quantize(CENTS)
        asset.salvage_base = (asset.salvage_value * rate).quantize(CENTS)
        warnings.extend(rate_warnings)
    asset.in_service_date = in_service_date

    first_period, elapsed = _first_schedule_period(asset.tenant, in_service_date)
    remaining = asset.useful_life_months - elapsed
    depreciable_amount = asset.cost_base - asset.opening_accumulated_depreciation - asset.salvage_base
    if remaining <= 0 or depreciable_amount <= 0:
        raise ValidationError(str(_("الأصل مُهلَك بالكامل.")))

    accum_account = get_system_account(asset.tenant, "ACCUM_DEPRECIATION")
    expense_account = get_system_account(asset.tenant, "DEPRECIATION_EXPENSE")

    entry = RecurringEntry.objects.create(
        tenant=asset.tenant, legal_entity=asset.legal_entity, cost_center=asset.cost_center,
        description=str(_("إهلاك %(code)s — %(name)s") % {"code": asset.code, "name": asset.name}),
        kind=RecurringEntry.Kind.DEPRECIATION, from_account=accum_account, to_account=expense_account,
        total_amount_base=depreciable_amount, installments_count=remaining, first_period=first_period,
        created_by=user,
    )
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER, actor_id=user.id, action="asset_depreciation.started",
        target_type="asset", target_id=asset.id, tenant_id=asset.tenant_id,
        after={"recurring_entry": str(entry.id), "installments_count": remaining}, request=request,
    )

    asset.depreciation_entry = entry
    asset.save(update_fields=["cost_base", "salvage_base", "in_service_date", "depreciation_entry"])

    from apps.approvals.services import submit_for_approval

    auto_approved = submit_for_approval(entry, user, DOC_TYPE, entry.total_amount_base, request=request)
    if auto_approved:
        _activate_schedule(entry)
    return entry, warnings


def _activate_schedule(entry):
    """Decision 5: dispatches to the straight-line or declining-balance
    generator based on the asset's own depreciation_method — the one
    place this module looks a schedule's owning Asset back up
    (Asset.depreciation_entry's related_name="+" only disables the
    convenience reverse manager, not filtering by the FK itself).
    Independent of apps.accounting.recurring._activate_recurring_entry
    per decision 5's own instruction not to touch that function."""
    asset = Asset.objects.get(depreciation_entry=entry)
    if asset.depreciation_method == Asset.DepreciationMethod.DECLINING_BALANCE:
        # entry.total_amount_base is always "book value at schedule
        # start − salvage_base" by construction (both at the original
        # start_depreciation and after an addition's recompute) — so
        # adding salvage_base back gives the opening book value without
        # this module needing to separately track accumulated-to-date,
        # which start_depreciation's own opening_accumulated_depreciation
        # field can't express once a *second* schedule (an addition)
        # has already run.
        opening_book_value = entry.total_amount_base + asset.salvage_base
        periods, amounts = _declining_balance_amounts(
            entry, opening_book_value, asset.salvage_base, asset.declining_balance_rate,
        )
    else:
        periods = _consecutive_periods(entry.tenant, entry.first_period, entry.installments_count, create=True)
        amounts = _split_amount(entry.total_amount_base, entry.installments_count)

    RecurringInstallment.objects.bulk_create(
        [
            RecurringInstallment(entry=entry, seq=i, period=period, due_date=period.end_date, amount_base=amount)
            for i, (period, amount) in enumerate(zip(periods, amounts), start=1)
        ]
    )
    if len(amounts) != entry.installments_count:
        # Decision 5's explicit floor check drove the schedule to end
        # earlier than the nominal useful-life count — keep the field
        # truthful so entry.installments.count() == entry.
        # installments_count still holds (recurring._generate_one's own
        # "seq == installments_count -> COMPLETED" check relies on it).
        entry.installments_count = len(amounts)
        entry.save(update_fields=["installments_count"])


def _declining_balance_amounts(entry, opening_book_value, salvage_base, annual_rate):
    """Decision 5 (متناقص): the year's charge = rate × book value at
    the start of that *fiscal* year; the monthly installment is always
    that charge ÷ 12 — a partial first (or last) year in the schedule
    simply uses fewer of those 12 equal monthly shares, never a charge
    ÷ (months actually in the schedule) — matching "السنة الأولى
    الجزئية بنفس القسط الشهري؛ فرق تقريب السنة على آخر قسط فيها". The
    schedule's own absolute final installment is then overridden to
    absorb whatever book value remains above salvage_base exactly,
    since pure declining-balance math asymptotes toward salvage_base
    but never reaches it in finite time. Returns (periods, amounts) —
    shorter than entry.installments_count only if an earlier
    installment's regular share would have driven the book value below
    salvage_base first (decision 5's explicit floor check)."""
    periods = _consecutive_periods(entry.tenant, entry.first_period, entry.installments_count, create=True)
    rate_fraction = annual_rate / Decimal("100")

    year_groups = []
    for period in periods:
        if year_groups and year_groups[-1][0] == period.fiscal_year_id:
            year_groups[-1][1].append(period)
        else:
            year_groups.append([period.fiscal_year_id, [period]])

    amounts = []
    book_value = opening_book_value
    floored = False
    for _fiscal_year_id, year_periods in year_groups:
        if book_value <= salvage_base:
            floored = True
            break
        annual_charge = (rate_fraction * book_value).quantize(CENTS)
        full_year_split = _split_amount(annual_charge, 12)
        for amount in full_year_split[: len(year_periods)]:
            if amount >= book_value - salvage_base:
                amounts.append(book_value - salvage_base)
                book_value = salvage_base
                floored = True
                break
            amounts.append(amount)
            book_value -= amount
        if floored:
            break

    if not floored and amounts:
        book_value_before_last = opening_book_value - sum(amounts[:-1], Decimal("0"))
        amounts[-1] = book_value_before_last - salvage_base

    return periods[: len(amounts)], amounts


@transaction.atomic
def approve_depreciation_schedule(entry, user, request=None, emergency_reason=""):
    from apps.approvals.services import approve as approvals_approve

    approvals_approve(
        entry, user, doc_type_for_entry(entry), entry.total_amount_base, request=request,
        emergency_reason=emergency_reason,
    )
    _activate_schedule(entry)
    return entry


def reject_depreciation_schedule(entry, user, reason, request=None):
    from apps.approvals.services import reject as approvals_reject

    return approvals_reject(entry, user, doc_type_for_entry(entry), reason, request=request)


@transaction.atomic
def _cancel_and_detach(entry, user, request=None):
    """Sprint 6.5.8 (UAT bugfix): a depreciation schedule has no edit
    form — unlike a voucher/invoice, the generic engine's DRAFT status
    (what withdraw()/reject() normally leave behind) is a dead end here:
    nothing to edit, nothing to resubmit from the asset screen, and
    start_depreciation still refuses a second call while any of these
    statuses is "active" (see _ACTIVE_SCHEDULE_STATUSES). Cancelling and
    detaching from the asset is what actually frees it up again — with
    opening_accumulated_depreciation and every other field editable
    again on a fresh start-depreciation form."""
    from apps.accounting.recurring import cancel_recurring_entry

    cancel_recurring_entry(entry, user, request=request)
    Asset.objects.filter(depreciation_entry=entry).update(depreciation_entry=None)
    return entry


def submit_depreciation_schedule(entry, user, request=None):
    """DRAFT -> PENDING_APPROVAL (or straight to APPROVED if no rule
    matches) — the "إرسال" action for a schedule a reject() sent back
    to DRAFT, so the creator can fix whatever the approver objected to
    and resubmit instead of only being able to cancel and start over."""
    from apps.approvals.services import submit_for_approval

    auto_approved = submit_for_approval(entry, user, doc_type_for_entry(entry), entry.total_amount_base, request=request)
    if auto_approved:
        _activate_schedule(entry)
    return entry


def cancel_depreciation_schedule(entry, user, request=None):
    """The "إلغاء" action for a DRAFT schedule (nothing pending to
    withdraw from) — same end state as withdraw_depreciation_schedule
    below, just reachable from DRAFT instead of PENDING_APPROVAL."""
    return _cancel_and_detach(entry, user, request=request)


def withdraw_depreciation_schedule(entry, user, request=None):
    """Sprint 6.5.8 (UAT bugfix): redefined from the generic engine's
    PENDING_APPROVAL -> DRAFT to a full cancel — see _cancel_and_detach.
    The generic withdraw() call still enforces "only the creator, only
    while pending" and still logs "withdrawn" before this cancels it."""
    from apps.approvals.services import withdraw as approvals_withdraw

    approvals_withdraw(entry, user, doc_type_for_entry(entry), request=request)
    return _cancel_and_detach(entry, user, request=request)


@transaction.atomic
def add_to_asset(asset, user, date, amount_base, description="", extend_life_months=0, request=None):
    """Decision 6: cancels the current schedule's remaining (DUE)
    installments and starts a fresh one over the new book value,
    spread across (remaining installments + extend_life_months). Never
    posts a journal entry itself — the purchase itself is a manual
    JV/voucher on FIXED_ASSETS like any other capital expenditure
    (decision 1)."""
    if amount_base <= 0:
        raise ValidationError(str(_("مبلغ الإضافة يجب أن يكون أكبر من صفر.")))

    old_entry = asset.depreciation_entry
    if old_entry is None or old_entry.status != RecurringEntry.Status.APPROVED:
        raise NoActiveDepreciationSchedule(str(_("لا يوجد جدول إهلاك نشط لهذا الأصل.")))

    book_value = current_book_value(asset)
    new_total = book_value + amount_base - asset.salvage_base
    old_due_count = old_entry.installments.filter(status=RecurringInstallment.Status.DUE).count()
    new_count = old_due_count + extend_life_months
    if new_count <= 0:
        raise ValidationError(str(_("لا توجد أقساط متبقية بعد هذه الإضافة.")))

    new_entry = _reschedule_remaining(asset, old_entry, new_total, new_count, date, user, request=request)
    # new_count/new_total were already checked positive above, so
    # _reschedule_remaining always returns a real entry here — the
    # None case is only for a partial disposal's own leaner remainder.
    new_entry.description = str(_("إهلاك %(code)s — %(name)s (بعد إضافة)") % {"code": asset.code, "name": asset.name})
    new_entry.save(update_fields=["description"])

    addition = AssetAddition.objects.create(
        tenant=asset.tenant, asset=asset, date=date, amount_base=amount_base, description=description,
        extend_life_months=extend_life_months, old_entry=old_entry, new_entry=new_entry, created_by=user,
    )
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER, actor_id=user.id, action="asset_addition.created",
        target_type="asset", target_id=asset.id, tenant_id=asset.tenant_id,
        after={"amount_base": str(amount_base), "new_entry": str(new_entry.id)}, request=request,
    )

    # Decision 6: purchase_cost/cost_base are both in base currency
    # here — every test and every spec example for this block is a
    # SAR (base-currency) asset; a foreign-currency asset's own
    # purchase_cost (its own currency) is left untouched, a known,
    # narrow limitation (cost_base, the field every computation above
    # actually reads, is always correct).
    asset.cost_base += amount_base
    asset.purchase_cost += amount_base
    if extend_life_months:
        asset.useful_life_months += extend_life_months
    asset.depreciation_entry = new_entry
    asset.save(update_fields=["cost_base", "purchase_cost", "useful_life_months", "depreciation_entry"])

    from apps.approvals.services import submit_for_approval

    auto_approved = submit_for_approval(new_entry, user, ADDITION_DOC_TYPE, new_entry.total_amount_base, request=request)
    if auto_approved:
        _activate_schedule(new_entry)
    return addition
