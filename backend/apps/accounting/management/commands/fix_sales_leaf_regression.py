from django.core.management.base import BaseCommand, CommandError

from apps.accounting.models import Account
from apps.platform.models import AuditLog
from apps.platform.services import log_action
from apps.tenants.models import Tenant


class Command(BaseCommand):
    """Sprint 7.0.2 (incident #6 fix — docs/SYSTEM_ANALYSIS.md §11):
    migration 0027 (sprint 6.5, 2026-09-26) parented DISPOSAL_GAIN_LOSS
    directly under SALES ("4000") for tenants where "4000" was already
    an active-posting leaf — can_post went False for SALES with no
    event logged anywhere, silently disabling invoice issuance for
    fatma/acme/sprint15test since that date (confirmed: none of the
    three has issued an invoice since).

    Fix: give DISPOSAL_GAIN_LOSS a proper, non-postable parent instead
    of SALES. SALES becomes a leaf again immediately. Not one posted
    JournalLine — on SALES or on DISPOSAL_GAIN_LOSS itself — is ever
    touched; this only ever reparents DISPOSAL_GAIN_LOSS, nothing else.

    Refuses outright (no partial action) if SALES has any OTHER child
    besides DISPOSAL_GAIN_LOSS — that would be a different, uninspected
    situation this command isn't scoped to handle blindly."""

    help = "One-off: move DISPOSAL_GAIN_LOSS off of SALES onto a new non-postable category account, restoring SALES to a leaf."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", action="append", required=True, help="Repeatable tenant subdomain.")
        parser.add_argument("--reason", required=True)

    def handle(self, *args, **options):
        for subdomain in options["tenant"]:
            tenant = Tenant.objects.get(subdomain=subdomain)
            sales = Account.objects.get(tenant=tenant, system_key="SALES")
            dgl = Account.objects.get(tenant=tenant, system_key="DISPOSAL_GAIN_LOSS")

            if dgl.parent_id != sales.id:
                self.stdout.write(f"{subdomain}: DISPOSAL_GAIN_LOSS is not parented under SALES — nothing to do.")
                continue

            other_children = sales.children.exclude(id=dgl.id)
            if other_children.exists():
                raise CommandError(
                    f"{subdomain}: SALES has other child/children besides DISPOSAL_GAIN_LOSS "
                    f"({[c.code for c in other_children]}) — refusing to act blindly; investigate first."
                )

            new_parent, created = Account.objects.get_or_create(
                tenant=tenant,
                code="4950",
                defaults={
                    "name": "أرباح وإيرادات أخرى",
                    "type": sales.type,  # same type as DISPOSAL_GAIN_LOSS/SALES — no aggregation change
                    "is_system": True,
                    "allow_posting": False,
                    "allow_manual_posting": False,
                },
            )

            before_parent_id = dgl.parent_id
            dgl.parent = new_parent
            dgl.save(update_fields=["parent"])

            log_action(
                actor_type=AuditLog.ActorType.PLATFORM,
                actor_id=None,
                action="account.rehome_parent",
                target_type="account",
                target_id=dgl.id,
                tenant_id=tenant.id,
                before={"parent_id": str(before_parent_id), "parent_code": sales.code},
                after={"parent_id": str(new_parent.id), "parent_code": new_parent.code},
            )

            sales.refresh_from_db()
            self.stdout.write(
                self.style.SUCCESS(
                    f"{subdomain}: DISPOSAL_GAIN_LOSS moved under {new_parent.code} "
                    f"({'created' if created else 'existing'}); SALES.can_post is now {sales.can_post} — {options['reason']}"
                )
            )
