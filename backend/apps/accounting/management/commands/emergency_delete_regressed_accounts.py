from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_datetime

from apps.accounting.models import Account, JournalLine
from apps.platform.models import AuditLog
from apps.platform.services import log_action


class Command(BaseCommand):
    """Sprint 7.0.1 incident (docs/SYSTEM_ANALYSIS.md §11): one-off,
    tightly-scoped correction for the VAT_OUTPUT/equity-root can_post
    regression from the night of 2026-10-04. add_missing_system_
    accounts' old fallback rule parented five new system accounts
    under each of 12 live tenants' own ACTIVE-POSTING LEAF accounts
    (VAT_OUTPUT at code "2100", the equity root at code "3000"). Since
    Account.can_post depends on is_leaf (`not self.children.exists()`,
    computed from the DEFAULT manager — see below), both accounts
    silently stopped accepting any new posting, breaking every new
    invoice for those 12 tenants from the moment of that deploy.

    These rows are brand new, hours old, with zero JournalLine
    references — not "مرحَّل" (posted/reconciled data). Deleting them
    undoes a structural mistake before anything ever used it; it is
    not a correction to posted accounting data.

    Real (hard) delete, not soft-delete, deliberately: Account.is_leaf/
    can_post read `self.children.exists()` through Account's plain
    default manager, which does NOT exclude soft-deleted rows (the
    only deleted_at filtering anywhere in this project is at the
    ViewSet/API layer — apps/common/viewsets.py — never on the model's
    own manager or any reverse FK accessor). Soft-deleting these rows
    would leave VAT_OUTPUT/the equity root exactly as broken as they
    are now. Hard deletion of accounting rows is otherwise never done
    in this project; this is the one explicitly owner-authorized
    exception, scoped by two conditions this command enforces itself
    (not just documents): created strictly after the given cutoff, and
    zero JournalLine rows — refuses outright if either condition would
    be violated for even one candidate."""

    help = (
        "One-off: delete the accounts that regressed VAT_OUTPUT/equity-root can_post tonight. "
        "Requires --created-after, --system-key (repeatable), and --reason."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--created-after", required=True,
            help="ISO datetime; only rows created strictly after this are even considered.",
        )
        parser.add_argument(
            "--system-key", action="append", required=True,
            help="Repeatable — only accounts with one of these system_keys are considered.",
        )
        parser.add_argument(
            "--tenant", action="append", default=None,
            help="Repeatable tenant subdomain — restricts to these tenants specifically. "
            "Omit only when --created-after/--system-key alone already uniquely identify the "
            "regression (the first pass of this incident didn't need it; the second pass, "
            "scoping the SAME afternoon run's RETAINED_EARNINGS/OPENING_BALANCE creation down to "
            "only the 12 tenants where it was an actual regression, did).",
        )
        parser.add_argument("--reason", required=True)

    def handle(self, *args, **options):
        cutoff = parse_datetime(options["created_after"])
        if cutoff is None:
            raise CommandError(f"Could not parse --created-after={options['created_after']!r} as an ISO datetime.")

        candidates = Account.objects.filter(created_at__gt=cutoff, system_key__in=options["system_key"])
        if options["tenant"]:
            candidates = candidates.filter(tenant__subdomain__in=options["tenant"])
        candidates = list(candidates.select_related("tenant"))
        total = len(candidates)
        with_lines = [a for a in candidates if JournalLine.objects.filter(account=a).exists()]
        if with_lines:
            raise CommandError(
                f"Refusing: {len(with_lines)} of {total} candidate account(s) already have JournalLine "
                f"row(s) — not safe to delete. First one: tenant={with_lines[0].tenant_id} "
                f"code={with_lines[0].code}."
            )

        self.stdout.write(
            f"Deleting {total} account(s) (created after {cutoff.isoformat()}, "
            f"keys={options['system_key']}, zero journal lines each — verified above)."
        )
        for account in candidates:
            log_action(
                actor_type=AuditLog.ActorType.PLATFORM,
                actor_id=None,
                action="account.emergency_delete",
                target_type="account",
                target_id=account.id,
                tenant_id=account.tenant_id,
                before={
                    "code": account.code, "name": account.name, "system_key": account.system_key,
                    "parent_id": str(account.parent_id), "created_at": account.created_at.isoformat(),
                },
                after=None,
            )
            self.stdout.write(f"  {account.tenant.subdomain}: deleting {account.code} {account.name} ({account.system_key}) — {options['reason']}")
            account.delete()

        self.stdout.write(self.style.SUCCESS(f"Deleted {total} account(s)."))
