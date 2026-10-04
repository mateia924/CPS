import json
import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.accounting.models import Account, JournalLine
from apps.accounting.services import AUTOMATED_POSTING_SYSTEM_KEYS
from apps.tenants.models import Tenant

# Same "/docs mounted read-only" convention as apps.tenants.management.
# commands.migrate's own BACKUPS_LOG_PATH — infra/docker-compose.dev.yml
# and docker-compose.local.yml both mount ../docs:/docs:ro. A committed
# exception, never an environment variable or a silent skip — see the
# file's own header.
EXCEPTIONS_PATH = Path(os.environ.get("CPS_CHART_HEALTH_EXCEPTIONS_PATH", "/docs/ops/chart_health_exceptions.json"))


def _load_exceptions():
    if not EXCEPTIONS_PATH.exists():
        return set()
    with EXCEPTIONS_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    return {(e["tenant"], e["system_key"]) for e in data.get("exceptions", [])}


class Command(BaseCommand):
    """Sprint 7.0.2 (incident #5 — docs/SYSTEM_ANALYSIS.md §11): turns
    the lesson of the whole incident into a standing check instead of
    a one-time fix. Account.can_post is a COMPUTED property
    (is_leaf -> `not self.children.exists()`), so a tenant's own chart
    can silently disable a posting path with no event logged anywhere
    — the exact way the night's own regression went undetected for
    hours, and the exact way migration 0027 (sprint 6.5, 2026-09-26)
    silently broke invoicing for 3 real tenants that nobody has
    noticed in over a week, because nobody happened to issue a new
    invoice for any of them since.

    Finds every account that is, at once: (1) tagged with a system_key
    in AUTOMATED_POSTING_SYSTEM_KEYS (an automated path posts TO this
    exact account directly — never CUSTOMERS/SUPPLIERS/BANKS/etc.,
    which only ever parent a per-party/per-instrument sub-ledger),
    (2) can_post is False (an automated posting attempt through it
    would be rejected right now), and (3) carries its own JournalLine
    row(s) (it was a real, directly-posted-to account at some point —
    distinguishes a genuine landmine from a plain category header that
    was always just a header).

    Reports every hit (tenant, account, system_key) — a data-quality
    finding, never auto-fixed here: whose chart this is and what the
    right fix looks like (a new category node above it, matching
    add_missing_system_accounts' own 7.0.2 design) is the owner's call,
    not a default this command applies silently.

    --fail-on-findings (scripts/deploy.sh always passes this): exits
    non-zero if anything is found — every tenant a real deploy ever
    touches is, by this project's own definition, live. Without the
    flag (a manual/audit run), it only reports; exit code stays 0.

    Exceptions (docs/ops/chart_health_exceptions.json — a committed
    file, never an environment variable, same pattern as the archived-
    tenant exclusion in add_missing_system_accounts): a (tenant,
    system_key) pair listed there is still printed every run, as an
    accepted exception, never silently dropped — it just no longer
    counts toward --fail-on-findings. Empty by default; an entry is
    added only when the owner explicitly decides to accept a specific
    tenant's chart shape as-is rather than fix it."""

    help = "Find accounts where an automated posting path is silently disabled by the tenant's own chart shape."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fail-on-findings", action="store_true",
            help="Exit non-zero if any finding is reported (scripts/deploy.sh always passes this).",
        )

    def handle(self, *args, **options):
        exceptions = _load_exceptions()
        findings = []
        accepted = []
        for tenant in Tenant.objects.exclude(status=Tenant.Status.ARCHIVED):
            accounts = Account.objects.filter(
                tenant=tenant, system_key__in=AUTOMATED_POSTING_SYSTEM_KEYS
            )
            for account in accounts:
                if account.can_post:
                    continue
                own_lines = JournalLine.objects.filter(account=account).count()
                if own_lines == 0:
                    continue
                row = (tenant.subdomain, account.code, account.system_key, own_lines)
                if (tenant.subdomain, account.system_key) in exceptions:
                    accepted.append(row)
                else:
                    findings.append(row)

        for subdomain, code, system_key, own_lines in accepted:
            self.stdout.write(
                f"  {subdomain}: account {code} ({system_key}) — ACCEPTED EXCEPTION "
                f"(docs/ops/chart_health_exceptions.json), {own_lines} existing journal line(s)"
            )

        if not findings:
            self.stdout.write(self.style.SUCCESS(f"check_chart_health: 0 findings ({len(accepted)} accepted exception(s))."))
            return

        self.stdout.write(
            self.style.WARNING(
                f"check_chart_health: {len(findings)} finding(s) — an automated posting path is "
                "silently disabled for the account(s) below. Not auto-fixed; review each tenant's "
                "own chart and decide (e.g. insert a non-postable category node above it, matching "
                "add_missing_system_accounts' own 7.0.2 design), or add a committed exception to "
                "docs/ops/chart_health_exceptions.json if the owner deliberately accepts it as-is."
            )
        )
        for subdomain, code, system_key, own_lines in findings:
            self.stdout.write(f"  {subdomain}: account {code} ({system_key}) — {own_lines} existing journal line(s)")

        if options["fail_on_findings"]:
            raise CommandError(f"{len(findings)} chart-health finding(s) on live tenant(s) — see above.")
