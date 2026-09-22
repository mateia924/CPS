"""Second layer of defense behind nginx's IP-only `limit_req` (see
infra/nginx/nginx.conf) on the auth endpoints named in ARCH_REVIEW_1.md
debt #9: /api/auth/login/, /api/auth/register/, /api/platform/auth/login/.

Keys on IP+email (not IP alone) so one attacker can't exhaust a shared
office IP's quota for every tenant, and one attacker can't exhaust a
single victim email's quota from many IPs without also being caught by
the per-IP nginx layer. django-ratelimit's cache-based counter lives in
Django's "default" cache (Redis, see config.settings.CACHES), so it is
shared correctly across every gunicorn worker — a LocMemCache default
would count each worker separately and undercount.
"""

from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django_ratelimit.core import is_ratelimited
from rest_framework.response import Response

RATE = "5/m"


def _client_ip(request):
    # Single-hop nginx (infra/nginx/nginx.conf) always sets
    # X-Forwarded-For to the real client IP; falls back to REMOTE_ADDR
    # for requests that reach the backend directly (tests, direct
    # container access).
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def check_auth_ratelimit(request, group, email):
    """Returns a 429 Response (Arabic detail) if this (ip, email) pair
    has exceeded 5 POSTs/minute on `group`; otherwise None."""
    if not settings.RATELIMIT_ENABLE:
        return None
    key = f"{_client_ip(request)}:{(email or '').strip().lower()}"
    limited = is_ratelimited(
        request,
        group=group,
        key=lambda g, r: key,
        rate=RATE,
        method="POST",
        increment=True,
    )
    if limited:
        return Response(
            {"detail": _("محاولات كثيرة جدًا. حاول مرة أخرى بعد دقيقة.")},
            status=429,
        )
    return None
