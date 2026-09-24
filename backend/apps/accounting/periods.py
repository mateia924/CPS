"""Sprint 6.1 (docs/SYSTEM_ANALYSIS.md 3.9, sprint-6.md decisions 1-4):
fiscal years and periods — the single gate every posting/save date must
clear, plus the year/period lifecycle (create, close, reopen, lock).

Non-overlap between a tenant's fiscal years, and the no-gap/no-overlap
sequencing of a year's periods, are validated here in Python rather
than as Postgres exclusion constraints (`ExclusionConstraint` needs the
`btree_gist` extension enabled — a new infra dependency this project
doesn't otherwise need; the app-level check already gives the exact
"400 بذكر الفترتين" error shape the spec asks for, and every write path
goes through these functions, never a raw `FiscalYear.objects.create`).
"""

import calendar
from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from .models import FiscalPeriod, FiscalYear


class FiscalYearBoundariesLocked(Exception):
    """Raised by update_fiscal_year_boundaries when a POSTED/REVERSED
    entry already exists in the year — the view maps this to 409."""


class PeriodLocked(Exception):
    """Raised by reopen_period when the period is already LOCKED
    (decision 4: never reopenable via any API) — the view maps this to
    409, distinct from the ordinary 400 a ValidationError gets."""


def _add_months(d, months):
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _generate_period_ranges(start_date, end_date, period_length, custom_period_end_dates=None):
    """Returns a list of (start, end) date pairs covering exactly
    [start_date, end_date] with no gap or overlap, by construction —
    the caller (create_fiscal_year_with_periods) still runs
    _validate_period_sequence on the result as a hard self-check."""
    if period_length not in ("monthly", "quarterly", "custom"):
        raise ValidationError({"period_length": [str(_("Must be one of: monthly, quarterly, custom."))]})

    if period_length == "custom":
        if not custom_period_end_dates:
            raise ValidationError(
                {"custom_period_end_dates": [str(_("At least one end date is required for a custom period length."))]}
            )
        ranges = []
        cursor = start_date
        for end in sorted(custom_period_end_dates):
            if end < cursor:
                raise ValidationError(
                    {"custom_period_end_dates": [str(_("Period end dates must be strictly increasing."))]}
                )
            ranges.append((cursor, end))
            cursor = end + timedelta(days=1)
        if ranges[-1][1] != end_date:
            raise ValidationError(
                {"custom_period_end_dates": [str(_("The last period must end exactly on the fiscal year's own end date."))]}
            )
        return ranges

    step = 1 if period_length == "monthly" else 3
    ranges = []
    cursor = start_date
    while True:
        period_end = _add_months(cursor, step) - timedelta(days=1)
        if period_end >= end_date:
            ranges.append((cursor, end_date))
            break
        ranges.append((cursor, period_end))
        cursor = period_end + timedelta(days=1)
    return ranges


def _validate_period_sequence(start_date, end_date, ranges):
    if not ranges:
        raise ValidationError(str(_("A fiscal year needs at least one period.")))
    if ranges[0][0] != start_date:
        raise ValidationError(
            str(_("The first period must start on the fiscal year's own start date (%(date)s).")) % {"date": start_date}
        )
    if ranges[-1][1] != end_date:
        raise ValidationError(
            str(_("The last period must end on the fiscal year's own end date (%(date)s).")) % {"date": end_date}
        )
    for previous, current in zip(ranges, ranges[1:]):
        if current[0] != previous[1] + timedelta(days=1):
            raise ValidationError(
                str(
                    _(
                        "Periods %(a)s..%(b)s and %(c)s..%(d)s leave a gap or overlap "
                        "— each period must start the day after the previous one ends."
                    )
                )
                % {"a": previous[0], "b": previous[1], "c": current[0], "d": current[1]}
            )


@transaction.atomic
def create_fiscal_year_with_periods(
    tenant, name, start_date, end_date, period_length="monthly", custom_period_end_dates=None, is_auto_created=False
):
    """Decision 1: no overlap with an existing fiscal year of this
    tenant; periods generated per `period_length` and re-validated for
    gap/overlap/coverage before anything is saved."""
    if end_date <= start_date:
        raise ValidationError({"end_date": [str(_("The end date must be after the start date."))]})

    overlapping = FiscalYear.objects.filter(
        tenant=tenant, start_date__lte=end_date, end_date__gte=start_date
    ).first()
    if overlapping is not None:
        raise ValidationError(
            str(_("This range overlaps an existing fiscal year: %(name)s (%(start)s..%(end)s)."))
            % {"name": overlapping.name, "start": overlapping.start_date, "end": overlapping.end_date}
        )

    ranges = _generate_period_ranges(start_date, end_date, period_length, custom_period_end_dates)
    _validate_period_sequence(start_date, end_date, ranges)

    year = FiscalYear.objects.create(
        tenant=tenant, name=name, start_date=start_date, end_date=end_date, is_auto_created=is_auto_created
    )
    periods = [
        FiscalPeriod(fiscal_year=year, seq=i, start_date=s, end_date=e)
        for i, (s, e) in enumerate(ranges, start=1)
    ]
    FiscalPeriod.objects.bulk_create(periods)
    return year


def seed_fiscal_year_for_tenant(tenant, start_date=None):
    """Decision 2: the calendar-year default — every tenant gets one of
    these at registration, and the migration/beat task below reach for
    it as the fallback shape (12 open monthly periods)."""
    year = (start_date or date(date.today().year, 1, 1)).year
    return create_fiscal_year_with_periods(
        tenant=tenant,
        name=str(year),
        start_date=date(year, 1, 1),
        end_date=date(year, 12, 31),
        period_length="monthly",
        is_auto_created=True,
    )


@transaction.atomic
def update_fiscal_year_boundaries(year, name, start_date, end_date, period_length="monthly", custom_period_end_dates=None):
    """Decision 1: "تعديل الحدود مسموح فقط ولا قيد POSTED بتاريخ داخل
    السنة" — once a real POSTED/REVERSED entry exists anywhere in the
    year's *current* range, its boundaries (and therefore its periods)
    are frozen; the only way forward from there is closing periods
    normally. Safe to fully discard and regenerate periods otherwise —
    nothing has been recorded against any of them yet."""
    from .models import JournalEntry

    posted_exists = JournalEntry.objects.filter(
        tenant_id=year.tenant_id,
        date__gte=year.start_date,
        date__lte=year.end_date,
        status__in=["posted", "reversed"],
    ).exists()
    if posted_exists:
        raise FiscalYearBoundariesLocked(
            str(_("This fiscal year already has posted documents — its boundaries can no longer be edited."))
        )

    if end_date <= start_date:
        raise ValidationError({"end_date": [str(_("The end date must be after the start date."))]})

    overlapping = (
        FiscalYear.objects.filter(tenant_id=year.tenant_id, start_date__lte=end_date, end_date__gte=start_date)
        .exclude(pk=year.pk)
        .first()
    )
    if overlapping is not None:
        raise ValidationError(
            str(_("This range overlaps an existing fiscal year: %(name)s (%(start)s..%(end)s)."))
            % {"name": overlapping.name, "start": overlapping.start_date, "end": overlapping.end_date}
        )

    ranges = _generate_period_ranges(start_date, end_date, period_length, custom_period_end_dates)
    _validate_period_sequence(start_date, end_date, ranges)

    year.periods.all().delete()
    year.name = name
    year.start_date = start_date
    year.end_date = end_date
    year.save(update_fields=["name", "start_date", "end_date"])
    periods = [
        FiscalPeriod(fiscal_year=year, seq=i, start_date=s, end_date=e) for i, (s, e) in enumerate(ranges, start=1)
    ]
    FiscalPeriod.objects.bulk_create(periods)
    return year


def assert_open_period(tenant, on_date):
    """Decision 3: the single date gate. Returns the covering
    FiscalPeriod, or raises a 400-shaped ValidationError in Arabic."""
    period = (
        FiscalPeriod.objects.filter(fiscal_year__tenant=tenant, start_date__lte=on_date, end_date__gte=on_date)
        .select_related("fiscal_year")
        .first()
    )
    if period is None:
        raise ValidationError(str(_("No fiscal period covers the date %(date)s.")) % {"date": on_date})
    if period.status != FiscalPeriod.Status.OPEN:
        raise ValidationError(
            str(_("The date %(date)s falls in a closed period: %(period)s.")) % {"date": on_date, "period": str(period)}
        )
    return period


def _previous_period(period):
    """"سابقتها" — the immediately preceding period by date, across
    fiscal-year boundaries (a going concern's periods are one
    continuous timeline, not year-siloed for this purpose)."""
    return (
        FiscalPeriod.objects.filter(fiscal_year__tenant=period.fiscal_year.tenant_id, end_date__lt=period.start_date)
        .order_by("-end_date")
        .first()
    )


def close_period(period, user, note="", acknowledge_warnings=False):
    """Decision 13 (sprint 6.7): the full BLOCK/WARN/INFO checklist —
    replaces this function's original 6.1 form (previous period closed
    + no unposted document only). Kept here, under this same name, so
    every existing caller (the view, other blocks' tests) picks up the
    stricter behavior automatically; the real implementation lives in
    period_close.py to keep this file's own scope to the year/period
    CRUD + lifecycle primitives."""
    from .period_close import close_period as _close_period_with_checklist

    return _close_period_with_checklist(period, user, note=note, acknowledge_warnings=acknowledge_warnings)


def _log_period_action(period, user, action, before_status, after_status):
    from apps.platform.models import AuditLog
    from apps.platform.services import log_action

    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER,
        actor_id=user.id if user else None,
        action=action,
        target_type="fiscal_period",
        target_id=period.id,
        tenant_id=period.fiscal_year.tenant_id,
        before={"status": before_status},
        after={"status": after_status},
    )


def reopen_period(period, user, reason):
    # Decision 4: "LOCKED ... لا تُفتح عبر أي API" — a distinct 409, not
    # the generic 400 an ordinary wrong-state attempt gets.
    if period.status == FiscalPeriod.Status.LOCKED:
        raise PeriodLocked(str(_("A permanently locked period can never be reopened.")))
    if period.status != FiscalPeriod.Status.CLOSED:
        raise ValidationError(str(_("Only a closed period can be reopened.")))
    if not reason:
        raise ValidationError(str(_("A reason is required to reopen a period.")))

    from django.utils import timezone

    period.status = FiscalPeriod.Status.OPEN
    period.reopened_by = user
    period.reopened_at = timezone.now()
    period.reopened_reason = reason
    period.save(update_fields=["status", "reopened_by", "reopened_at", "reopened_reason"])
    _log_period_action(period, user, "fiscal_period.reopened", before_status="closed", after_status="open")

    if period.fiscal_year.status != FiscalYear.Status.OPEN:
        period.fiscal_year.status = FiscalYear.Status.OPEN
        period.fiscal_year.save(update_fields=["status"])
    return period


def lock_period(period, user, attestation):
    if period.status != FiscalPeriod.Status.CLOSED:
        raise ValidationError(str(_("Only a closed period can be locked.")))
    if not attestation or len(attestation.strip()) < 20:
        raise ValidationError(str(_("A written attestation of at least 20 characters is required to lock a period.")))

    from django.utils import timezone

    period.status = FiscalPeriod.Status.LOCKED
    period.locked_by = user
    period.locked_at = timezone.now()
    period.lock_attestation = attestation
    period.save(update_fields=["status", "locked_by", "locked_at", "lock_attestation"])
    _log_period_action(period, user, "fiscal_period.locked", before_status="closed", after_status="locked")

    _lock_year_if_all_periods_locked(period.fiscal_year)
    return period


def _lock_year_if_all_periods_locked(fiscal_year):
    all_locked = not fiscal_year.periods.exclude(status=FiscalPeriod.Status.LOCKED).exists()
    if all_locked and fiscal_year.status != FiscalYear.Status.LOCKED:
        fiscal_year.status = FiscalYear.Status.LOCKED
        fiscal_year.save(update_fields=["status"])


def create_next_fiscal_year_for_tenant(tenant, latest=None):
    """The single-tenant computation behind create_next_fiscal_year_if_due
    (the beat) — extracted in 6.4 so a recurring-entry schedule that
    outruns the fiscal periods that currently exist (decision 9: "تُنشأ
    سنة تالية تلقائيًا إن لزم بالقرار 2") can force the same "next year,
    same length, contiguous" creation for one tenant on demand, not just
    when the beat's own 30-day-horizon condition is met."""
    if latest is None:
        latest = FiscalYear.objects.filter(tenant=tenant).order_by("-end_date").first()
    if latest is None:
        # decision 2: "لا مستأجر بلا سنة مالية في أي لحظة" — should
        # never happen post-migration, but a defensive fallback.
        from django.utils import timezone

        return seed_fiscal_year_for_tenant(tenant, start_date=timezone.localdate())
    next_start = latest.end_date + timedelta(days=1)
    length_days = (latest.end_date - latest.start_date).days
    next_end = next_start + timedelta(days=length_days)
    period_length = "quarterly" if latest.periods.count() <= 4 else "monthly"
    return create_fiscal_year_with_periods(
        tenant=tenant,
        name=str(next_start.year) if next_start.year == next_end.year else f"{next_start.year}-{next_end.year}",
        start_date=next_start,
        end_date=next_end,
        period_length=period_length,
        is_auto_created=True,
    )


def create_next_fiscal_year_if_due():
    """Decision 2's beat: for every tenant whose latest fiscal year ends
    within 30 days and has no successor yet, create the next year (same
    length, contiguous, `is_auto_created=True`). Idempotent — a tenant
    already covered past the 30-day horizon is skipped."""
    from django.utils import timezone

    from apps.tenants.models import Tenant

    today = timezone.localdate()
    horizon = today + timedelta(days=30)
    created = []
    for tenant in Tenant.objects.all():
        latest = FiscalYear.objects.filter(tenant=tenant).order_by("-end_date").first()
        if latest is not None and latest.end_date > horizon:
            continue
        created.append(create_next_fiscal_year_for_tenant(tenant, latest))
    return created
