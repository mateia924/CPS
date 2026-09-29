# Sprint 6.5.15 (UAT item 3): apps.accounting.periods.
# create_next_fiscal_year_for_tenant used to compute a new auto-created
# fiscal year's end date from the previous year's *day count*, which
# drifts by a day across a leap-year boundary and compounds on every
# later auto-created year — confirmed live on tenant "fatma"'s FY2028
# (drifted to end 2028-12-30) and the tail of a 36-month declining-
# balance depreciation schedule (installments 29-36 landing on
# 2028-12-30, 2029-01-30, 02-27, ... instead of true month-ends).
#
# This repairs every tenant with such a drifted, still-clean (nothing
# posted/generated against it) auto-created fiscal year: the year and
# its periods are deleted and regenerated with correct calendar-month
# boundaries, and every affected RecurringInstallment still in DUE
# status (never posted — a GENERATED one is never touched, matching
# "لا تعديل على أي مستند مرحَّل إطلاقًا") is re-dated from its own
# schedule anchor (seq=1's own due_date, always correct) rather than
# from whatever period it happened to land in, since the drifted
# periods' own boundaries are exactly what's being thrown away. Amounts
# are never touched — only due_date and the period FK it must stay
# consistent with.
#
# Migrations never import live app code (project convention): _add_months
# and the monthly _generate_period_ranges are duplicated inline, exactly
# matching apps.accounting.periods.
import calendar
from datetime import date, timedelta

from django.db import migrations


def _add_months(d, months):
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _month_end(d):
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def _months_span(year_start, year_end):
    return (year_end.year - year_start.year) * 12 + (year_end.month - year_start.month) + 1


def fix_drifted_auto_fiscal_years(apps, schema_editor):
    FiscalYear = apps.get_model("accounting", "FiscalYear")
    FiscalPeriod = apps.get_model("accounting", "FiscalPeriod")
    RecurringInstallment = apps.get_model("accounting", "RecurringInstallment")

    report = []
    for tenant_id in set(FiscalYear.objects.filter(is_auto_created=True).values_list("tenant_id", flat=True)):
        years = list(FiscalYear.objects.filter(tenant_id=tenant_id).order_by("start_date"))
        # Corrected boundaries cascade forward: once year i-1 is found
        # drifted, year i's own "expected" boundary must be computed
        # from i-1's CORRECTED dates, never its still-drifted stored
        # ones — otherwise a second drifted year in the same chain
        # (exactly fatma's real FY"2028-2029") computes an "expected"
        # start that coincidentally matches its own already-wrong
        # stored start (both derived from the same wrong FY2028.end_date),
        # and drift silently goes undetected past the first year.
        corrected_boundary = {years[0].id: (years[0].start_date, years[0].end_date)}
        drifted_years = []
        for i in range(1, len(years)):
            prev, year = years[i - 1], years[i]
            prev_start, prev_end = corrected_boundary[prev.id]
            expected_start = prev_end + timedelta(days=1)
            expected_end = _add_months(expected_start, _months_span(prev_start, prev_end)) - timedelta(days=1)
            if not year.is_auto_created or (year.start_date == expected_start and year.end_date == expected_end):
                corrected_boundary[year.id] = (year.start_date, year.end_date)
                continue
            if RecurringInstallment.objects.filter(period__fiscal_year=year, status="generated").exists():
                # A real posted document already lives here — never
                # touched, no matter how it got drifted. Still counts
                # as this chain's new anchor going forward.
                corrected_boundary[year.id] = (year.start_date, year.end_date)
                continue
            corrected_boundary[year.id] = (expected_start, expected_end)
            drifted_years.append(year)

        if not drifted_years:
            continue

        drifted_ids = [y.id for y in drifted_years]
        due_rows = list(
            RecurringInstallment.objects.filter(period__fiscal_year_id__in=drifted_ids, status="due")
            .values("id", "entry_id", "seq", "amount_base")
        )
        RecurringInstallment.objects.filter(id__in=[r["id"] for r in due_rows]).delete()
        FiscalPeriod.objects.filter(fiscal_year_id__in=drifted_ids).delete()
        deleted_names = [y.name for y in drifted_years]
        FiscalYear.objects.filter(id__in=drifted_ids).delete()

        def ensure_period_for(target_date):
            period = FiscalPeriod.objects.filter(
                fiscal_year__tenant_id=tenant_id, start_date__lte=target_date, end_date__gte=target_date
            ).first()
            if period is not None:
                return period
            latest = FiscalYear.objects.filter(tenant_id=tenant_id).order_by("-end_date").first()
            while latest.end_date < target_date:
                next_start = latest.end_date + timedelta(days=1)
                next_end = _add_months(next_start, _months_span(latest.start_date, latest.end_date)) - timedelta(days=1)
                new_year = FiscalYear.objects.create(
                    tenant_id=tenant_id,
                    name=(str(next_start.year) if next_start.year == next_end.year else f"{next_start.year}-{next_end.year}"),
                    start_date=next_start, end_date=next_end, is_auto_created=True,
                )
                cursor, seq, periods = next_start, 1, []
                while cursor <= next_end:
                    p_end = _add_months(cursor, 1) - timedelta(days=1)
                    if p_end >= next_end:
                        p_end = next_end
                    periods.append(FiscalPeriod(fiscal_year=new_year, seq=seq, start_date=cursor, end_date=p_end))
                    cursor = p_end + timedelta(days=1)
                    seq += 1
                FiscalPeriod.objects.bulk_create(periods)
                latest = new_year
            return FiscalPeriod.objects.get(
                fiscal_year__tenant_id=tenant_id, start_date__lte=target_date, end_date__gte=target_date
            )

        by_entry = {}
        for row in due_rows:
            by_entry.setdefault(row["entry_id"], []).append(row)

        recreated = 0
        for entry_id, rows in by_entry.items():
            anchor_due_date = (
                RecurringInstallment.objects.filter(entry_id=entry_id, seq=1).values_list("due_date", flat=True).first()
            )
            if anchor_due_date is None:
                continue
            anchor_month_start = _month_end(anchor_due_date).replace(day=1)
            new_rows = []
            for row in sorted(rows, key=lambda r: r["seq"]):
                true_due_date = _month_end(_add_months(anchor_month_start, row["seq"] - 1))
                correct_period = ensure_period_for(true_due_date)
                new_rows.append(
                    RecurringInstallment(
                        entry_id=entry_id, seq=row["seq"], period=correct_period,
                        due_date=true_due_date, amount_base=row["amount_base"], status="due",
                    )
                )
            RecurringInstallment.objects.bulk_create(new_rows)
            recreated += len(new_rows)

        report.append({"tenant_id": str(tenant_id), "deleted_years": deleted_names, "recreated_installments": recreated})

    print(f"[sprint 6.5.15 item 3] fixed drifted auto-created fiscal years and re-dated not-yet-generated installments: {report}")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0030_backfill_blank_normal_balance"),
    ]

    operations = [
        migrations.RunPython(fix_drifted_auto_fiscal_years, noop),
    ]
