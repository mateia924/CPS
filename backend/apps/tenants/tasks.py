from celery import shared_task
from django.conf import settings
from django.utils import timezone

from apps.platform.models import AuditLog
from apps.platform.services import log_action

from .models import Tenant


@shared_task
def auto_suspend_past_due_tenants():
    """Sprint 6 (block 6.0, item 6 — CFO_REVIEW_1 §7 Q10 gap): daily
    beat — any tenant PAST_DUE for more than settings.PAST_DUE_GRACE_DAYS
    is auto-transitioned to SUSPENDED (read-only, already enforced by
    TenantAwareJWTAuthentication — this task only flips the status)."""
    cutoff = timezone.now() - timezone.timedelta(days=settings.PAST_DUE_GRACE_DAYS)
    tenants = Tenant.objects.filter(status=Tenant.Status.PAST_DUE, past_due_since__lte=cutoff)
    count = 0
    for tenant in tenants:
        before_status = tenant.status
        tenant.status = Tenant.Status.SUSPENDED
        tenant.save(update_fields=["status"])
        log_action(
            actor_type=AuditLog.ActorType.PLATFORM,
            actor_id=None,
            action="tenant.auto_suspend_past_due",
            target_type="tenant",
            target_id=tenant.id,
            tenant_id=tenant.id,
            before={"status": before_status, "past_due_since": tenant.past_due_since.isoformat()},
            after={"status": tenant.status},
        )
        count += 1
    return count
