from django.core.management.base import BaseCommand

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
    transition in this project — no row is ever deleted."""

    help = "Archive (soft) every tenant whose subdomain starts with 'smoke-'. Touches no other tenant."

    def handle(self, *args, **options):
        tenants = Tenant.objects.filter(subdomain__startswith="smoke-").exclude(
            status=Tenant.Status.ARCHIVED
        )
        if not tenants.exists():
            self.stdout.write("No smoke-* tenants to archive.")
            return
        for tenant in tenants:
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
            self.stdout.write(self.style.SUCCESS(f"Archived {tenant.subdomain} ({tenant.id})"))
