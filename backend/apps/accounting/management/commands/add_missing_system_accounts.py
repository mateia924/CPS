from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounting.models import Account
from apps.accounting.services import CONTROL_SYSTEM_KEYS, SYSTEM_ACCOUNT_SPECS
from apps.tenants.models import Tenant

# Sprint 7.0.2 (incident, 2026-10-04 — docs/SYSTEM_ANALYSIS.md §11): the
# parent_code on every SYSTEM_ACCOUNT_SPECS entry is always one of
# these five chart roots. Used only when that exact code doesn't exist
# yet on a tenant's chart — see _resolve_parent's own docstring for why
# this is now the ONLY thing ever created as a stand-in parent.
_CATEGORY_NAME_BY_PARENT_CODE = {
    "1000": "الأصول",
    "2000": "الالتزامات",
    "3000": "حقوق الملكية",
    "4000": "الإيرادات",
    "5000": "المصروفات",
}


class Command(BaseCommand):
    """Sprint 7.0 (D1), rewritten in 7.0.1 and again in 7.0.2 (rule-11
    incidents #4 and #5 — see docs/SYSTEM_ANALYSIS.md §11): idempotent,
    covers every system_key this project has ever introduced
    (SYSTEM_ACCOUNT_SPECS), not just inventory's five new ones —
    replaces the old pattern of a brand-new one-off data migration
    every time a system account is added (0006/0016/0022/0027). Safe
    to run on every deploy, forever: scripts/deploy.sh calls it after
    `manage.py setup_rls`.

    For a tenant that already has a given system_key, the only change
    ever made is flipping an existing account's allow_manual_posting to
    False if that key has since become a CONTROL_SYSTEM_KEYS member
    (COGS's own case: existing trading/manufacturing/holding tenants
    already had a COGS account, created before COGS was a control
    account).

    Parent resolution (7.0.2 — see _resolve_parent): the spec's own
    parent_code if it exists, otherwise a BRAND-NEW, never-postable
    category account created at that exact code — never an existing
    account of a merely-matching type. 7.0.1's own fallback ("the first
    root account of the same type") was exactly the bug that broke
    invoicing for 12 live tenants the night of 2026-10-04:
    VAT_OUTPUT and the equity root were both active-posting LEAF
    accounts that fallback picked as a parent, and Account.can_post
    depends on is_leaf (`not self.children.exists()`, read through the
    plain default manager — no amount of allow_posting staying True
    saves a parent from this) — the instant each gained a child, every
    new invoice and every future equity posting for those 12 tenants
    started failing. A brand-new category node with zero history can
    never do that to an existing posting path.

    Archived tenants (7.0.1 follow-up): excluded from processing
    entirely, but named and counted explicitly in the output every run
    — an archived tenant has no live chart anyone is extending or
    posting against. A DECLARED exclusion, not a silent skip.
    """

    help = "Create any missing system account for every tenant, and fix allow_manual_posting on existing ones (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", default=None, help="Only this tenant's subdomain, instead of every tenant.")

    def handle(self, *args, **options):
        tenants = Tenant.objects.exclude(status=Tenant.Status.ARCHIVED)
        if options["tenant"]:
            tenants = tenants.filter(subdomain=options["tenant"])

        archived = Tenant.objects.filter(status=Tenant.Status.ARCHIVED)
        if options["tenant"]:
            archived = archived.filter(subdomain=options["tenant"])
        archived_names = sorted(archived.values_list("subdomain", flat=True))
        if archived_names:
            self.stdout.write(
                f"Excluding {len(archived_names)} archived tenant(s) (not processed): {', '.join(archived_names)}"
            )

        created_count = 0
        fixed_count = 0
        failures = []
        tenants_processed = 0
        created_per_tenant = {}

        for tenant in tenants.iterator():
            tenants_processed += 1
            for spec in SYSTEM_ACCOUNT_SPECS:
                outcome, detail = self._ensure_account(tenant, spec)
                if outcome == "created":
                    created_count += 1
                    created_per_tenant[tenant.subdomain] = created_per_tenant.get(tenant.subdomain, 0) + 1
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

        summary = (
            f"{tenants_processed} tenant(s) processed, {len(archived_names)} excluded (archived), "
            f"{created_count} account(s) created across {len(created_per_tenant)} tenant(s) "
            f"({created_per_tenant}), {fixed_count} existing account(s) corrected to "
            "allow_manual_posting=False"
        )
        if failures:
            self.stdout.write(self.style.ERROR(f"{summary}, {len(failures)} FAILURE(S)."))
        else:
            self.stdout.write(self.style.SUCCESS(f"{summary}, 0 failures."))

        if failures:
            raise CommandError(
                f"{len(failures)} required system account(s) could not be created for "
                f"{len({t for t, _k, _d in failures})} tenant(s) — see the errors above. "
                "This command never skips a key silently; fix the underlying error, then rerun."
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

        try:
            parent, placement = self._resolve_parent(tenant, spec)

            code = spec["code"]
            if Account.objects.filter(tenant=tenant, code=code).exists():
                # Same collision-avoidance as 0022/0027: a pre-existing
                # custom account already sits on this exact code —
                # never overwrite it, take the next free code instead.
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
        except Exception as exc:  # noqa: BLE001 — defense in depth; see class docstring
            return "failed", f"{type(exc).__name__}: {exc}"

        return "created", f"at {code} under parent {parent.code} ({placement})"

    def _resolve_parent(self, tenant, spec):
        """Returns (parent_account, description). 7.0.2: NEVER attaches
        a new child to an account that is a genuine active-posting
        leaf (`can_post` True) — regardless of whether it was found by
        the spec's own exact parent_code or would have been a
        same-type fallback. A pure category header (already non-leaf,
        or explicitly allow_posting=False) is always safe to attach
        under, exact-code match or not — attaching another child to an
        already-non-postable node changes nothing about any existing
        posting path.

        When the exact code either doesn't exist, or exists but is
        still postable, a brand-new, never-postable category account
        is created instead — tagged with a synthetic, never-colliding
        system_key (`_CATEGORY_ROOT_<parent_code>`) so every later spec
        sharing the same parent_code reuses this exact node instead of
        creating a second one (needed specifically for the case where
        the expected code was taken by a leaf and the stand-in had to
        go on a different code — the common case, expected code free,
        already self-stabilizes by landing the stand-in AT that exact
        code, which the plain exact-match lookup then finds directly
        on the very next spec)."""
        stand_in_key = f"_CATEGORY_ROOT_{spec['parent_code']}"
        existing_stand_in = Account.objects.filter(tenant=tenant, system_key=stand_in_key).first()
        if existing_stand_in is not None:
            return existing_stand_in, f"existing stand-in category account {existing_stand_in.code}"

        parent = Account.objects.filter(tenant=tenant, code=spec["parent_code"]).first()
        if parent is not None and not parent.can_post:
            return parent, f"exact parent code {spec['parent_code']}"

        name = _CATEGORY_NAME_BY_PARENT_CODE[spec["parent_code"]]
        code = spec["parent_code"]
        if Account.objects.filter(tenant=tenant, code=code).exists():
            # The expected code is taken by a genuine active-posting
            # leaf (confirmed above) — never place the stand-in there;
            # same numeric-suffix collision-avoidance used elsewhere.
            suffix = 1
            while Account.objects.filter(tenant=tenant, code=f"{code[:-1]}{suffix}").exists():
                suffix += 1
            code = f"{code[:-1]}{suffix}"

        new_parent = Account.objects.create(
            tenant=tenant,
            code=code,
            name=name,
            type=spec["type"],
            system_key=stand_in_key,
            is_system=True,
            allow_posting=False,
            allow_manual_posting=False,
        )
        if parent is None:
            reason = f"created new category account {code} ({name}) — a new node, never an existing one, is always used as the stand-in parent"
        else:
            reason = (
                f"created new category account {code} ({name}) instead of reusing existing "
                f"account {spec['parent_code']}, which is still an active posting leaf (can_post=True)"
            )
        return new_parent, reason
