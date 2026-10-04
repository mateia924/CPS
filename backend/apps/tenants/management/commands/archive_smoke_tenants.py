from django.core.management.base import BaseCommand, CommandError

from apps.accounting.models import JournalEntry
from apps.platform.models import AuditLog
from apps.platform.services import log_action

from ...models import Tenant


class Command(BaseCommand):
    """§11 standing rule: every session that creates a temporary
    smoke-* tenant (manual/API testing that must never write to a live
    tenant) ends with this command. The "smoke-" prefix is hardcoded —
    there is no option to pass a different one, so this can never be
    pointed at a real tenant by a typo'd flag or argument. Soft-archive
    only (Tenant.Status.ARCHIVED), same as any other tenant lifecycle
    transition in this project — no row is ever deleted.

    Sprint 6.6.3b: `manage.py seed_perf`'s own perf-baseline tenant
    deliberately does NOT start with "smoke-" (the original
    "smoke-perf" was auto-archived by this exact command, the hard
    way, right after a 100k-line seed) — it's excluded from this
    command's reach by name, not by a special case here.

    Sprint 7.0.2 follow-up: a historical audit (2026-10-04) found 19
    already-archived smoke-* tenants silently carrying 57 POSTED,
    never-reversed JournalEntry rows (627,000.00 combined) — "archiving
    is cleanup" had never actually been true, only assumed, since this
    command archived a tenant's STATUS without ever looking at its
    books. Reversing a entry changes its own status away from POSTED
    (see DocumentStateMixin/apps.accounting.services.
    reverse_journal_entry — the original becomes REVERSED, the
    reversal itself is the new POSTED row), so `status=POSTED` alone
    is exactly "posted and still un-reversed", same query as the
    historical audit used. This command now refuses to archive any
    tenant carrying such a row unless --force is given with a written
    --reason — and that reason is logged (AuditLog), never a silent
    bypass. --force does not reverse anything itself; it only lets a
    known, named debt be archived anyway, on the record."""

    help = "Archive (soft) every tenant whose subdomain starts with 'smoke-'. Touches no other tenant."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force", action="store_true",
            help="Archive a tenant anyway even if it has POSTED, never-reversed JournalEntry rows. "
            "Requires --reason.",
        )
        parser.add_argument(
            "--reason", default=None,
            help="Required with --force — logged into AuditLog, naming why the unreversed entries "
            "are being left behind.",
        )

    def handle(self, *args, **options):
        force = options["force"]
        reason = options["reason"]
        if force and not reason:
            raise CommandError("--force requires --reason — a silent bypass of unreversed postings is not allowed.")

        tenants = Tenant.objects.filter(subdomain__startswith="smoke-").exclude(
            status=Tenant.Status.ARCHIVED
        )
        if not tenants.exists():
            self.stdout.write("No smoke-* tenants to archive.")
            return

        blocked = []
        for tenant in tenants:
            unreversed = list(
                JournalEntry.objects.filter(tenant=tenant, status=JournalEntry.Status.POSTED)
                .order_by("number")
            )
            if unreversed and not force:
                blocked.append((tenant, unreversed))
                continue

            before_status = tenant.status
            tenant.status = Tenant.Status.ARCHIVED
            tenant.save(update_fields=["status"])
            log_action(
                actor_type=AuditLog.ActorType.PLATFORM,
                actor_id=None,
                action="tenant.archive_smoke",
                target_type="tenant",
                target_id=tenant.id,
                tenant_id=tenant.id,
                before={"status": before_status},
                after={"status": tenant.status},
            )
            if unreversed:
                # force=True and reason is set — the earlier guard above would
                # have raised otherwise, so this path only runs with a reason.
                log_action(
                    actor_type=AuditLog.ActorType.PLATFORM,
                    actor_id=None,
                    action="tenant.archive_smoke_forced_with_unreversed_entries",
                    target_type="tenant",
                    target_id=tenant.id,
                    tenant_id=tenant.id,
                    before={
                        "unreversed_entry_numbers": [e.number for e in unreversed],
                        "unreversed_entry_count": len(unreversed),
                    },
                    after={"reason": reason},
                )
                self.stdout.write(self.style.WARNING(
                    f"Archived {tenant.subdomain} ({tenant.id}) WITH {len(unreversed)} unreversed "
                    f"posted entr{'y' if len(unreversed) == 1 else 'ies'} left behind (--force, reason={reason!r})."
                ))
            else:
                self.stdout.write(self.style.SUCCESS(f"Archived {tenant.subdomain} ({tenant.id})"))

        if blocked:
            lines = []
            for tenant, entries in blocked:
                names = ", ".join(e.number or str(e.id) for e in entries)
                lines.append(f"  {tenant.subdomain}: {len(entries)} unreversed posted entr"
                              f"{'y' if len(entries) == 1 else 'ies'} — {names}")
            raise CommandError(
                "Refusing to archive the following tenant(s) — they carry POSTED journal entries "
                "that were never reversed. Reverse them first, or re-run with --force --reason "
                "\"...\" to archive anyway (logged, not silent):\n" + "\n".join(lines)
            )
