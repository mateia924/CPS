from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounting.models import Account
from apps.accounting.services import CONTROL_SYSTEM_KEYS, SYSTEM_ACCOUNT_SPECS
from apps.tenants.models import Tenant


class Command(BaseCommand):
    """Sprint 7.0 (D1): idempotent, covers every system_key this
    project has ever introduced (SYSTEM_ACCOUNT_SPECS), not just
    inventory's five new ones — replaces the old pattern of a brand-new
    one-off data migration every time a system account is added
    (0006/0016/0022/0027). Safe to run on every deploy, forever:
    scripts/deploy.sh now calls it after `manage.py setup_rls`.

    For a tenant that already has a given system_key, the only change
    ever made is flipping an existing account's allow_manual_posting to
    False if that key has since become a CONTROL_SYSTEM_KEYS member
    (COGS's own case here: existing trading/manufacturing/holding
    tenants already had a COGS account, created before COGS was a
    control account)."""

    help = "Create any missing system account for every tenant, and fix allow_manual_posting on existing ones (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", default=None, help="Only this tenant's subdomain, instead of every tenant.")

    def handle(self, *args, **options):
        tenants = Tenant.objects.all()
        if options["tenant"]:
            tenants = tenants.filter(subdomain=options["tenant"])

        created_count = 0
        fixed_count = 0
        for tenant in tenants.iterator():
            for spec in SYSTEM_ACCOUNT_SPECS:
                created, fixed = self._ensure_account(tenant, spec)
                created_count += created
                fixed_count += fixed

        self.stdout.write(
            self.style.SUCCESS(
                f"{created_count} account(s) created, {fixed_count} existing account(s) "
                "corrected to allow_manual_posting=False."
            )
        )

    @transaction.atomic
    def _ensure_account(self, tenant, spec):
        existing = Account.objects.filter(tenant=tenant, system_key=spec["system_key"]).first()
        if existing is not None:
            if spec["system_key"] in CONTROL_SYSTEM_KEYS and existing.allow_manual_posting:
                existing.allow_manual_posting = False
                existing.save(update_fields=["allow_manual_posting"])
                return 0, 1
            return 0, 0

        parent = Account.objects.filter(tenant=tenant, code=spec["parent_code"]).first()
        if parent is None:
            # A chart predating even the parent root (shouldn't happen
            # for a real tenant — every template has 1000/2000/3000/
            # 4000/5000 — but never crash a deploy over it).
            return 0, 0

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
        return 1, 0
