from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounting.models import Account
from apps.accounting.services import CONTROL_SYSTEM_KEYS, SYSTEM_ACCOUNT_SPECS
from apps.tenants.models import Tenant


class Command(BaseCommand):
    """Sprint 7.0 (D1), rewritten in 7.0.1 (rule-11 incident #4 — see
    docs/SYSTEM_ANALYSIS.md §11): idempotent, covers every system_key
    this project has ever introduced (SYSTEM_ACCOUNT_SPECS), not just
    inventory's five new ones — replaces the old pattern of a brand-new
    one-off data migration every time a system account is added
    (0006/0016/0022/0027). Safe to run on every deploy, forever:
    scripts/deploy.sh calls it after `manage.py setup_rls`.

    For a tenant that already has a given system_key, the only change
    ever made is flipping an existing account's allow_manual_posting to
    False if that key has since become a CONTROL_SYSTEM_KEYS member
    (COGS's own case: existing trading/manufacturing/holding tenants
    already had a COGS account, created before COGS was a control
    account).

    Parent resolution, declared (7.0.1 — the exact point 6.6.3's/the
    original 7.0 version silently skipped on): first try the spec's
    own literal parent_code. If that account doesn't exist — a chart
    predating today's numbering, or just a different one, which a
    multi-tenant product must expect rather than assume away — fall
    back to the first root account (no parent) of the SAME type. This
    is a deliberate, declared rule, not a guess: a brand-new control
    account always ends up under *some* account of its own type, never
    under an unrelated one. Every placement (exact-code or fallback)
    is printed by tenant and key. If NEITHER the exact code NOR any
    root account of that type exists at all (a tenant with no chart of
    that type whatsoever — e.g. a never-seeded test tenant), the key is
    recorded as a failure, printed loudly, and the command exits
    non-zero — it never reports success while quietly having skipped
    something.
    """

    help = "Create any missing system account for every tenant, and fix allow_manual_posting on existing ones (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", default=None, help="Only this tenant's subdomain, instead of every tenant.")

    def handle(self, *args, **options):
        tenants = Tenant.objects.all()
        if options["tenant"]:
            tenants = tenants.filter(subdomain=options["tenant"])

        created_count = 0
        fixed_count = 0
        failures = []

        for tenant in tenants.iterator():
            for spec in SYSTEM_ACCOUNT_SPECS:
                outcome, detail = self._ensure_account(tenant, spec)
                if outcome == "created":
                    created_count += 1
                    self.stdout.write(f"{tenant.subdomain}: created {spec['system_key']} {detail}")
                elif outcome == "fixed":
                    fixed_count += 1
                elif outcome == "failed":
                    failures.append((tenant.subdomain, spec["system_key"], detail))
                    self.stderr.write(
                        self.style.ERROR(f"{tenant.subdomain}: COULD NOT create {spec['system_key']} — {detail}")
                    )
                # outcome == "skipped": already exists and needs no fix
                # — the normal steady state, silent on purpose.

        self.stdout.write(
            self.style.SUCCESS(
                f"{created_count} account(s) created, {fixed_count} existing account(s) "
                "corrected to allow_manual_posting=False."
            )
        )

        if failures:
            raise CommandError(
                f"{len(failures)} required system account(s) could not be created for "
                f"{len({t for t, _k, _d in failures})} tenant(s) — see the errors above. "
                "This command never skips a key silently; fix the chart or the parent-"
                "resolution rule, then rerun."
            )

    @transaction.atomic
    def _ensure_account(self, tenant, spec):
        existing = Account.objects.filter(tenant=tenant, system_key=spec["system_key"]).first()
        if existing is not None:
            if spec["system_key"] in CONTROL_SYSTEM_KEYS and existing.allow_manual_posting:
                existing.allow_manual_posting = False
                existing.save(update_fields=["allow_manual_posting"])
                return "fixed", None
            return "skipped", None

        parent, placement = self._resolve_parent(tenant, spec)
        if parent is None:
            return "failed", placement

        code = spec["code"]
        if Account.objects.filter(tenant=tenant, code=code).exists():
            # Same collision-avoidance as 0022/0027: a pre-existing
            # custom account already sits on this exact code — never
            # overwrite it, take the next free code instead.
            suffix = 1
            while Account.objects.filter(tenant=tenant, code=f"{code[:-1]}{suffix}").exists():
                suffix += 1
            code = f"{code[:-1]}{suffix}"

        Account.objects.create(
            tenant=tenant,
            code=code,
            name=spec["name"],
            type=spec["type"],
            system_key=spec["system_key"],
            parent=parent,
            is_system=True,
            allow_manual_posting=spec["system_key"] not in CONTROL_SYSTEM_KEYS,
        )
        return "created", f"at {code} under parent {parent.code} ({placement})"

    def _resolve_parent(self, tenant, spec):
        """Returns (parent_account_or_None, description). See the
        class docstring for the declared rule."""
        parent = Account.objects.filter(tenant=tenant, code=spec["parent_code"]).first()
        if parent is not None:
            return parent, f"exact parent code {spec['parent_code']}"

        fallback = (
            Account.objects.filter(tenant=tenant, parent__isnull=True, type=spec["type"])
            .order_by("code")
            .first()
        )
        if fallback is not None:
            return fallback, (
                f"fallback: no account at parent code {spec['parent_code']}, used the first "
                f"root {spec['type']} account instead (code {fallback.code})"
            )

        return None, (
            f"no account at parent code {spec['parent_code']} and no root {spec['type']} "
            "account exists at all for this tenant"
        )
