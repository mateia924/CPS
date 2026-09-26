"""Sprint 6.4 (docs/SYSTEM_ANALYSIS.md 3.15.4, sprint-6.md decisions
9-10): "القيود الدورية" — prepaid expenses / deferred revenue /
accruals. A `RecurringEntry` is drafted with two accounts and a total
split across N installments; approval creates every installment row up
front for the consecutive fiscal periods starting at `first_period`
(creating the next fiscal year automatically if the schedule outruns
what already exists — decision 2); each installment is later generated
into its own POSTED `JournalEntry` independently, once its own period's
end_date is reached (Celery beat + on-demand), or SKIPPED (never
silently) if that period is CLOSED/LOCKED by then.
"""

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.numbering.services import next_document_number
from apps.platform.models import AuditLog
from apps.platform.services import log_action

from .models import (
    FiscalPeriod,
    FiscalYear,
    JournalEntry,
    JournalLine,
    RecurringEntry,
    RecurringInstallment,
)
from .periods import create_next_fiscal_year_for_tenant
from .services import CENTS

DOC_TYPE = "recurring_entry"


def _split_amount(total, count):
    """Decision 9: "الأقساط = الإجمالي ÷ العدد مقرَّبًا لمنزلتين
    والباقي على الأخير" — every installment but the last is the same
    rounded share; the last absorbs whatever rounding left over so the
    sum always equals `total` exactly."""
    share = (total / count).quantize(CENTS, rounding=ROUND_HALF_UP)
    amounts = [share] * (count - 1)
    amounts.append(total - share * (count - 1))
    return amounts


def preview_installments(total_amount_base, installments_count, first_period):
    """Decision 9's screen requirement — "معاينة جدول الأقساط قبل
    الحفظ": a pure, read-only computation (seq/period/due_date/amount),
    reused by both the API preview action and _activate_recurring_entry
    below so the two can never drift apart. Does NOT create any
    FiscalYear — `_consecutive_periods` is the only caller allowed to,
    since a preview must never have a side effect."""
    amounts = _split_amount(total_amount_base, installments_count)
    periods = _consecutive_periods(first_period.fiscal_year.tenant, first_period, installments_count, create=False)
    return [
        {"seq": i, "period": period, "due_date": period.end_date, "amount_base": amount}
        for i, (period, amount) in enumerate(zip(periods, amounts), start=1)
    ]


def _consecutive_periods(tenant, first_period, count, create=True):
    periods = [first_period]
    cursor = first_period
    while len(periods) < count:
        nxt = (
            FiscalPeriod.objects.filter(fiscal_year__tenant=tenant, start_date=cursor.end_date + timedelta(days=1))
            .select_related("fiscal_year")
            .first()
        )
        if nxt is None:
            if not create:
                # Preview mode: report only as far as periods already
                # exist — the real activation (create=True) is what
                # actually grows the calendar (decision 2).
                break
            latest_year = FiscalYear.objects.filter(tenant=tenant).order_by("-end_date").first()
            create_next_fiscal_year_for_tenant(tenant, latest_year)
            nxt = FiscalPeriod.objects.filter(
                fiscal_year__tenant=tenant, start_date=cursor.end_date + timedelta(days=1)
            ).select_related("fiscal_year").first()
        periods.append(nxt)
        cursor = nxt
    return periods


def create_recurring_entry(
    tenant, user, legal_entity, kind, description, from_account, to_account,
    total_amount_base, installments_count, first_period, cost_center=None, request=None,
):
    if installments_count < 1:
        raise ValidationError(_("عدد الأقساط يجب أن يكون 1 على الأقل."))
    if total_amount_base <= 0:
        raise ValidationError(_("الإجمالي يجب أن يكون أكبر من صفر."))
    for account in (from_account, to_account):
        if not account.can_post:
            raise ValidationError(
                _("لا يمكن الترحيل على الحساب %(code)s: إما أنه حساب أب له فروع أو أن الترحيل عليه معطّل.")
                % {"code": account.code}
            )

    entry = RecurringEntry.objects.create(
        tenant=tenant, legal_entity=legal_entity, description=description, kind=kind,
        from_account=from_account, to_account=to_account, cost_center=cost_center,
        total_amount_base=total_amount_base, installments_count=installments_count,
        first_period=first_period, created_by=user,
    )
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER, actor_id=user.id, action="recurring_entry.created",
        target_type="recurring_entry", target_id=entry.id, tenant_id=tenant.id, request=request,
    )
    return entry


@transaction.atomic
def submit_recurring_entry(entry, user, request=None):
    from apps.approvals.services import submit_for_approval

    if not entry.number:
        entry.number = next_document_number(entry.tenant, DOC_TYPE, entry.legal_entity, timezone.localdate())
        entry.save(update_fields=["number"])

    auto_approved = submit_for_approval(entry, user, DOC_TYPE, entry.total_amount_base, request=request)
    if auto_approved:
        _activate_recurring_entry(entry)
    return entry


@transaction.atomic
def approve_recurring_entry(entry, user, request=None, emergency_reason=""):
    from apps.approvals.services import approve as approvals_approve

    approvals_approve(
        entry, user, DOC_TYPE, entry.total_amount_base, request=request, emergency_reason=emergency_reason
    )
    _activate_recurring_entry(entry)
    return entry


def _activate_recurring_entry(entry):
    """Decision 9: "عند الاعتماد تُنشأ الأقساط للفترات المتتالية بدءًا
    من first_period" — runs once, the moment the schedule goes APPROVED
    (either via a real approval or the no-matching-rule auto-approve
    path submit_for_approval already handles for every other doc type)."""
    amounts = _split_amount(entry.total_amount_base, entry.installments_count)
    periods = _consecutive_periods(entry.tenant, entry.first_period, entry.installments_count, create=True)
    RecurringInstallment.objects.bulk_create(
        [
            RecurringInstallment(entry=entry, seq=i, period=period, due_date=period.end_date, amount_base=amount)
            for i, (period, amount) in enumerate(zip(periods, amounts), start=1)
        ]
    )


def reject_recurring_entry(entry, user, reason, request=None):
    from apps.approvals.services import reject as approvals_reject

    return approvals_reject(entry, user, DOC_TYPE, reason, request=request)


def withdraw_recurring_entry(entry, user, request=None):
    from apps.approvals.services import withdraw as approvals_withdraw

    return approvals_withdraw(entry, user, DOC_TYPE, request=request)


@transaction.atomic
def cancel_recurring_entry(entry, user, request=None):
    """Decision 9: "cancel يلغي الأقساط DUE فقط" — an already-GENERATED
    installment's posted JournalEntry is untouched (this is not a mass
    reversal), and a SKIPPED one stays SKIPPED (still visible/
    regenerable in the period-close checklist, 6.7)."""
    if entry.status not in (RecurringEntry.Status.APPROVED, RecurringEntry.Status.PENDING_APPROVAL, RecurringEntry.Status.DRAFT):
        raise ValidationError(_("لا يمكن إلغاء جدول مكتمل أو مُلغى بالفعل."))
    cancelled = entry.installments.filter(status=RecurringInstallment.Status.DUE).update(
        status=RecurringInstallment.Status.CANCELLED
    )
    entry.status = RecurringEntry.Status.CANCELLED
    entry.save(update_fields=["status"])
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER, actor_id=user.id, action="recurring_entry.cancelled",
        target_type="recurring_entry", target_id=entry.id, tenant_id=entry.tenant_id,
        after={"installments_cancelled": cancelled}, request=request,
    )
    return entry


def _generate_one(installment):
    entry = installment.entry
    journal_entry = JournalEntry.objects.create(
        tenant=entry.tenant, legal_entity=entry.legal_entity, date=installment.due_date,
        memo=str(
            _("قسط %(seq)s/%(total)s — %(description)s")
            % {"seq": installment.seq, "total": entry.installments_count, "description": entry.description}
        ),
        number=next_document_number(entry.tenant, "journal_entry", entry.legal_entity, installment.due_date),
        status=JournalEntry.Status.POSTED,
        source_type="recurring", source_id=entry.id,
        currency=entry.legal_entity.base_currency, exchange_rate=Decimal("1"),
    )
    JournalLine.objects.bulk_create(
        [
            JournalLine(
                entry=journal_entry, account=entry.to_account, cost_center=entry.cost_center,
                party=entry.to_account.party, currency=journal_entry.currency,
                debit_fc=installment.amount_base, debit=installment.amount_base,
            ),
            JournalLine(
                entry=journal_entry, account=entry.from_account, cost_center=entry.cost_center,
                party=entry.from_account.party, currency=journal_entry.currency,
                credit_fc=installment.amount_base, credit=installment.amount_base,
            ),
        ]
    )
    installment.status = RecurringInstallment.Status.GENERATED
    installment.journal_entry = journal_entry
    installment.generated_at = timezone.now()
    installment.save(update_fields=["status", "journal_entry", "generated_at"])

    if installment.seq == entry.installments_count:
        entry.status = RecurringEntry.Status.COMPLETED
        entry.save(update_fields=["status"])
    return journal_entry


@transaction.atomic
def regenerate_installment(installment, user, request=None):
    if installment.status != RecurringInstallment.Status.SKIPPED:
        raise ValidationError(_("لا يمكن إعادة التوليد إلا لقسط تم تخطّيه."))
    if installment.period.status != FiscalPeriod.Status.OPEN:
        raise ValidationError(_("لا يمكن إعادة التوليد إلا بعد إعادة فتح الفترة."))
    journal_entry = _generate_one(installment)
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER, actor_id=user.id, action="recurring_installment.regenerated",
        target_type="recurring_installment", target_id=installment.id, tenant_id=installment.entry.tenant_id,
        after={"journal_entry": str(journal_entry.id)}, request=request,
    )
    return installment


@transaction.atomic
def generate_due_installments(tenant=None, as_of=None, recurring_entry=None):
    """Decision 10: every DUE installment whose period's end_date has
    been reached — OPEN period -> POSTED (approval already happened at
    the schedule level, this is a system path, not a manual one); CLOSED/
    LOCKED -> SKIPPED with a reason, never a silent failure. Safe to run
    twice: a DUE row transitions to GENERATED/SKIPPED and is never
    picked up again by this same query.

    Sprint 6.5.7: `recurring_entry` narrows this to one schedule — the
    "توليد المستحق الآن" button on a single asset's depreciation tab
    reuses this exact function/logic instead of duplicating it, scoped
    to just that asset's `depreciation_entry`."""
    as_of = as_of or timezone.localdate()
    qs = RecurringInstallment.objects.filter(
        status=RecurringInstallment.Status.DUE, period__end_date__lte=as_of
    ).select_related("period", "entry", "entry__legal_entity")
    if tenant is not None:
        qs = qs.filter(entry__tenant=tenant)
    if recurring_entry is not None:
        qs = qs.filter(entry=recurring_entry)

    generated, skipped = 0, 0
    for installment in qs:
        if installment.period.status == FiscalPeriod.Status.OPEN:
            _generate_one(installment)
            generated += 1
        else:
            installment.status = RecurringInstallment.Status.SKIPPED
            installment.skip_reason = str(
                _("الفترة %(period)s بحالة %(status)s وقت التوليد.")
                % {"period": str(installment.period), "status": installment.period.get_status_display()}
            )
            installment.save(update_fields=["status", "skip_reason"])
            skipped += 1
    return {"generated": generated, "skipped": skipped}
