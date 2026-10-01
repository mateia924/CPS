import os
import time
import uuid
from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from apps.accounting.models import Account, JournalEntry, JournalLine
from apps.accounting.periods import seed_fiscal_year_for_tenant
from apps.accounting.services import seed_chart_of_accounts
from apps.common.models import DocumentStateMixin
from apps.organization.services import create_default_legal_entities
from apps.platform.models import Plan
from apps.tenants.models import Tenant, TenantFeatures


class Command(BaseCommand):
    """Sprint 6.6.3 (item 3): repeatable performance baseline — not a
    gate test (no pass/fail threshold enforced here), just a fixture +
    timings the sprint summary records and every future review re-runs
    by hand: `manage.py seed_perf --tenant perf-baseline --lines
    100000`.

    Bypasses the normal posting workflow entirely (bulk_create straight
    to POSTED) — this is about query performance on realistic *volume*,
    not re-testing posting correctness, which the rest of the suite
    already covers.

    Sprint 6.6.3b: the tenant name deliberately does NOT start with
    "smoke-" (the original "smoke-perf" was auto-archived by `make
    e2e`'s own cleanup step, which treats any "smoke-*" subdomain as
    its own disposable fixture — found live, the hard way, right after
    seeding 100k lines). Also refuses outright on staging/production —
    this is a dev-only fixture, never real UAT/customer data."""

    help = "Seed a tenant with N JournalLine rows and time the four report queries."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", default="perf-baseline")
        parser.add_argument("--lines", type=int, default=100_000)

    def handle(self, *args, **options):
        if os.environ.get("CPS_ENVIRONMENT") in ("staging", "production"):
            raise CommandError(
                "seed_perf refuses to run on staging/production — this is a dev-only "
                "performance fixture, never real UAT/customer data."
            )

        subdomain = options["tenant"]
        if subdomain.startswith("smoke-"):
            raise CommandError(
                "A 'smoke-*' subdomain is auto-archived by make e2e's own cleanup "
                "(apps.tenants.management.commands.archive_smoke_tenants) — pick a "
                "different name, e.g. the default 'perf-baseline'."
            )
        total_lines = options["lines"]
        if total_lines % 2 != 0:
            total_lines += 1

        tenant, created = Tenant.objects.get_or_create(
            subdomain=subdomain,
            defaults={"name": "Perf Seed Tenant", "plan": Plan.objects.get(code="enterprise")},
        )
        if created:
            TenantFeatures.objects.create(tenant=tenant)
            create_default_legal_entities(tenant, tenant.name)
            seed_chart_of_accounts(tenant)
            seed_fiscal_year_for_tenant(tenant, start_date=date(2026, 1, 1))
            self.stdout.write(f"Created tenant {subdomain}.")
        else:
            self.stdout.write(f"Reusing existing tenant {subdomain}.")

        legal_entity = tenant.legalentitys.filter(entity_type="branch").first()
        accounts = list(Account.objects.filter(tenant=tenant, children__isnull=True)[:2])
        if len(accounts) < 2:
            self.stderr.write(self.style.ERROR("Tenant's chart of accounts has fewer than 2 leaf accounts."))
            return
        debit_account, credit_account = accounts

        entries_count = total_lines // 2
        self.stdout.write(f"Seeding {entries_count} journal entries ({total_lines} lines)...")
        start_date = date(2026, 1, 1)
        batch_size = 5000
        entries_batch, lines_batch = [], []
        for i in range(entries_count):
            entry_id = uuid.uuid4()
            entry_date = start_date + timedelta(days=i % 300)
            entries_batch.append(
                JournalEntry(
                    id=entry_id, tenant=tenant, legal_entity=legal_entity, date=entry_date,
                    memo=f"Perf seed {i}", number=f"PERF-{i}",
                    status=DocumentStateMixin.Status.POSTED,
                )
            )
            lines_batch.append(JournalLine(entry_id=entry_id, account=debit_account, debit=100, credit=0))
            lines_batch.append(JournalLine(entry_id=entry_id, account=credit_account, debit=0, credit=100))
            if len(entries_batch) >= batch_size:
                JournalEntry.objects.bulk_create(entries_batch)
                JournalLine.objects.bulk_create(lines_batch)
                entries_batch, lines_batch = [], []
        if entries_batch:
            JournalEntry.objects.bulk_create(entries_batch)
            JournalLine.objects.bulk_create(lines_batch)
        self.stdout.write(self.style.SUCCESS("Seed complete."))

        self._time_reports(tenant, legal_entity)

    def _time_reports(self, tenant, legal_entity):
        from apps.accounting.models import FiscalPeriod
        from apps.accounting.period_close import period_checklist
        from apps.accounting.services import compute_trial_balance, ledger_lines
        from apps.reports.services import balance_sheet

        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM accounting_journalline")
            self.stdout.write(f"Total JournalLine rows in DB: {cursor.fetchone()[0]}")

        def _timed(label, fn):
            start = time.monotonic()
            fn()
            elapsed = time.monotonic() - start
            self.stdout.write(f"{label}: {elapsed:.3f}s")

        _timed("trial_balance", lambda: compute_trial_balance(tenant))
        _timed("balance_sheet", lambda: balance_sheet(tenant, as_of=date(2026, 12, 31)))
        account = Account.objects.filter(tenant=tenant, children__isnull=True).first()
        _timed("ledger_lines (one account, full year)", lambda: ledger_lines(tenant, account))

        period = FiscalPeriod.objects.filter(fiscal_year__tenant=tenant, start_date__lte=date(2026, 1, 15)).first()
        if period is not None:
            _timed("period_checklist", lambda: period_checklist(period))
