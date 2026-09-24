import calendar
from datetime import date

from django.db import migrations

# Sprint 6.1 (decision 2): "لا مستأجر بلا سنة مالية في أي لحظة" — every
# tenant that predates this migration gets calendar-year FiscalYears
# (12 open monthly periods each) covering at least 2026, extended to
# also cover its oldest/newest POSTED-or-REVERSED JournalEntry date if
# either falls outside 2026. Reimplemented here (not imported from
# apps.accounting.periods) per this app's own convention of not
# importing live app code into a data migration — see
# apps/access/migrations/0003_seed_permissions.py's note.


def _month_range(year, month):
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def backfill_fiscal_years(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    JournalEntry = apps.get_model("accounting", "JournalEntry")
    FiscalYear = apps.get_model("accounting", "FiscalYear")
    FiscalPeriod = apps.get_model("accounting", "FiscalPeriod")

    for tenant in Tenant.objects.all():
        if FiscalYear.objects.filter(tenant=tenant).exists():
            continue

        dates = list(
            JournalEntry.objects.filter(tenant=tenant, status__in=["posted", "reversed"]).values_list(
                "date", flat=True
            )
        )
        start_year = min([d.year for d in dates] + [2026])
        end_year = max([d.year for d in dates] + [2026])

        for year in range(start_year, end_year + 1):
            fiscal_year = FiscalYear.objects.create(
                tenant=tenant,
                name=str(year),
                start_date=date(year, 1, 1),
                end_date=date(year, 12, 31),
                status="open",
                is_auto_created=True,
            )
            periods = []
            for month in range(1, 13):
                start, end = _month_range(year, month)
                periods.append(
                    FiscalPeriod(fiscal_year=fiscal_year, seq=month, start_date=start, end_date=end, status="open")
                )
            FiscalPeriod.objects.bulk_create(periods)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0023_fiscalyear_fiscalperiod_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_fiscal_years, noop),
    ]
