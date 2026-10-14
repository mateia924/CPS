from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from apps.access.models import Role
from apps.approvals.defaults import DEFAULT_APPROVAL_RULES, seed_default_approval_rules
from apps.approvals.models import ApprovalRule
from apps.common.rls import set_local_tenant_id
from apps.tenants.models import Tenant


class Command(BaseCommand):
    """7.4 follow-up (docs/SYSTEM_ANALYSIS.md §11): add named default
    approval rules to ONE named tenant that was registered before
    registration seeded the full set.

    Deliberately narrow, unlike add_missing_system_accounts: adding an
    approval rule to a tenant in use changes its workflow immediately, so
    this is a per-tenant decision by the owner, never a sweep. One
    --subdomain (exact match, no filter over all tenants); every
    --doc-type spelled out; archived tenants refused. Rules come from the
    same definition registration uses (apps/approvals/defaults.py) via
    get_or_create, so a second run creates nothing.

    Safe for a single-active-user tenant: approvals.services exempts the
    only active user from the creator-can't-approve rule and logs the
    exemption — the new gate is one extra click, never a dead stop.
    """

    help = "Backfill named default approval rules on one named tenant (idempotent; prints before/after)."

    def add_arguments(self, parser):
        parser.add_argument("--subdomain", required=True, help="Exactly one tenant, by subdomain.")
        parser.add_argument(
            "--doc-type", action="append", required=True, dest="doc_types",
            help=f"Repeat per doc_type. One of: {', '.join(DEFAULT_APPROVAL_RULES)}.",
        )

    def handle(self, *args, **options):
        doc_types = list(dict.fromkeys(options["doc_types"]))
        unknown = [d for d in doc_types if d not in DEFAULT_APPROVAL_RULES]
        if unknown:
            raise CommandError(f"Not a default doc_type: {unknown}. Defaults: {list(DEFAULT_APPROVAL_RULES)}")
        try:
            tenant = Tenant.objects.get(subdomain=options["subdomain"])
        except Tenant.DoesNotExist as exc:
            raise CommandError(f"No tenant with subdomain {options['subdomain']!r}.") from exc
        if tenant.status == Tenant.Status.ARCHIVED:
            raise CommandError(f"{tenant.subdomain} is archived — refusing.")

        with transaction.atomic():
            with connection.cursor() as cursor:
                set_local_tenant_id(cursor, tenant.id)
            before = self._active_rules(tenant)
            self._print("BEFORE", tenant, before)
            seed_default_approval_rules(tenant, ApprovalRule=ApprovalRule, Role=Role, doc_types=doc_types)
            after = self._active_rules(tenant)
            self._print("AFTER", tenant, after)

        added = sorted(set(after) - set(before))
        self.stdout.write(f"added {len(added)}: {', '.join(added) or '(none — already present)'}")
        not_added = [d for d in doc_types if d not in after]
        if not_added:
            # get_or_create found an inactive/deleted rule, or no Owner role:
            # say so instead of reporting success.
            raise CommandError(f"Still not active after backfill: {not_added}")

    def _active_rules(self, tenant):
        rules = ApprovalRule.objects.filter(tenant=tenant, is_active=True, deleted_at__isnull=True)
        return {r.doc_type: (r.min_amount, r.required_role.name) for r in rules.select_related("required_role")}

    def _print(self, label, tenant, rules):
        self.stdout.write(f"{label} — {tenant.subdomain}: {len(rules)} active rule(s)")
        for doc_type in sorted(rules):
            min_amount, role = rules[doc_type]
            self.stdout.write(f"  {doc_type:<20} min={min_amount}  role={role}")
