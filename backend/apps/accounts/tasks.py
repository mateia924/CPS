"""Sprint 7.2.9 (§8.9, R-7.2.9.3): the request endpoint enqueues
send_password_reset_email_task unconditionally for any well-formed
(subdomain, email) pair and returns 200 immediately either way — every
account-existence branch (tenant found? user found?) happens in here,
on Celery's own clock, never on the HTTP response path. That is what
actually closes the timing side-channel a naive "look up now, respond
different" implementation would leave open even with an identical
response BODY: a real lookup+send takes measurably longer than an
early return, and that's enough to enumerate accounts from response
latency alone.

celery_worker runs on the unrestricted database role by design (see
infra/docker-compose.yml's own comment on that service) — no
`set_local_tenant_id` call here, same as every other cross-tenant
background task in this app (send_pending_approvals_digest, etc.)."""

import secrets
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


@shared_task
def send_password_reset_email_task(subdomain, email):
    from apps.tenants.models import Tenant

    from .models import PasswordResetToken, User
    from .services import build_tenant_url

    tenant = Tenant.objects.filter(subdomain=(subdomain or "").strip().lower()).first()
    if tenant is None:
        return
    user = User.objects.filter(tenant=tenant, email__iexact=(email or "").strip(), is_active=True).first()
    if user is None:
        return

    # R-7.2.9.2: issuing a new token invalidates every other
    # outstanding one for this user — deleting them is enough (a
    # deleted row can never match the confirm lookup again), no extra
    # "superseded" column needed beyond what §8.9 specified.
    PasswordResetToken.objects.filter(user=user, used_at__isnull=True).delete()

    raw_token = secrets.token_urlsafe(32)
    PasswordResetToken.objects.create(
        user=user,
        tenant=tenant,
        token_hash=PasswordResetToken.hash_token(raw_token),
        expires_at=timezone.now() + timedelta(minutes=settings.PASSWORD_RESET_TOKEN_TTL_MINUTES),
    )
    link = build_tenant_url(tenant, f"/reset-password?token={raw_token}")

    # R-7.2.9's §0.3: the raw token/link is never logged anywhere —
    # this call is the only place it exists outside the recipient's
    # own inbox, and Celery's own task-argument logging (if enabled)
    # never sees it either, since it isn't a task argument here.
    send_mail(
        subject=str(_("استرجاع كلمة السر — CPS")),
        message=str(
            _(
                "اضغط الرابط التالي لتعيين كلمة سر جديدة:\n%(link)s\n\n"
                "الرابط صالح لمدة %(minutes)s دقيقة.\n"
                "إن لم تطلب استرجاع كلمة السر، تجاهل هذه الرسالة."
            )
            % {"link": link, "minutes": settings.PASSWORD_RESET_TOKEN_TTL_MINUTES}
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
    )
