"""Sprint 6.6.2: 2FA enrollment/verification and session hygiene for
tenant users. `generate_totp_secret`/`verify_totp` are the exact same
functions apps.platform.services uses for PlatformUser — reused, not
copied (neither depends on which model owns the secret, both take
plain strings)."""

import base64
import re
import secrets
from datetime import timedelta
from io import BytesIO
from urllib.parse import urlsplit

import pyotp
import qrcode
import qrcode.image.svg
from django.conf import settings
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from apps.platform.services import generate_totp_secret, verify_totp  # noqa: F401 (re-exported)

from .models import BackupCode, UserSession

BACKUP_CODE_COUNT = 10


_IPV4_HOST_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")


def build_tenant_url(tenant, path):
    """Sprint 7.2.9 (R-7.2.9.5): a per-tenant link, never
    `settings.FRONTEND_BASE_URL` alone. `apps.approvals.tasks.
    _item_link` makes exactly that mistake today (registered, unfixed,
    out of this block's scope) — a link that lands on the bare domain
    leaves the user on a page with no idea which tenant it's for.
    Inserts the tenant's own subdomain in front of
    `FRONTEND_BASE_URL`'s host, same shape
    `frontend/src/lib/subdomain.ts` expects to parse back out.

    Mirrors that same file's own `IPV4_PATTERN` exemption: staging
    today has no domain of its own at all (served by raw IP on 3001,
    §8.9's own staging note) — `fatma.154.41.209.222` is not a
    resolvable hostname, prepending a subdomain label to an IP address
    produces a dead link, not a per-tenant one. An IP-shaped host
    (checked on the hostname alone, stripped of its port — unlike the
    frontend's `window.location.hostname`, `netloc` here still carries
    one) gets the bare host back, unprefixed, exactly the "no company
    identifier" case subdomain.ts already treats as its own
    no-subdomain branch."""
    scheme, netloc = urlsplit(settings.FRONTEND_BASE_URL)[:2]
    host = netloc.split(":")[0]
    if _IPV4_HOST_RE.match(host):
        return f"{scheme}://{netloc}{path}"
    return f"{scheme}://{tenant.subdomain}.{netloc}{path}"


def totp_provisioning_uri(user, secret):
    return pyotp.totp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="CPS")


def totp_qr_data_uri(provisioning_uri):
    """A self-contained `data:image/svg+xml;base64,...` QR image — no
    frontend QR library needed, same reasoning as every other
    Money/date-formatting decision in this project: one place renders
    it, correctly, once. SVG (not PNG) deliberately — qrcode's PNG path
    needs Pillow, a new binary dependency this doesn't otherwise need."""
    img = qrcode.make(provisioning_uri, image_factory=qrcode.image.svg.SvgPathImage)
    buf = BytesIO()
    img.save(buf)
    return "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()


def generate_backup_codes(user):
    """Creates BACKUP_CODE_COUNT fresh one-time codes, replacing any
    existing ones. Returns the plaintext codes — the ONLY time they're
    ever available; only sha256 hashes are stored."""
    BackupCode.objects.filter(user=user).delete()
    raw_codes = [secrets.token_hex(5) for _ in range(BACKUP_CODE_COUNT)]
    BackupCode.objects.bulk_create(
        [BackupCode(user=user, code_hash=BackupCode.hash_code(code)) for code in raw_codes]
    )
    return raw_codes


def consume_backup_code(user, code):
    code_hash = BackupCode.hash_code(code)
    updated = BackupCode.objects.filter(
        user=user, code_hash=code_hash, used_at__isnull=True
    ).update(used_at=timezone.now())
    return updated > 0


def user_requires_2fa_setup(user):
    """True if one of the user's roles is in the tenant's
    `require_2fa_for_roles` list and they haven't enrolled yet — the
    login response's own `requires_2fa_setup` flag forces the frontend
    to the setup screen on next login (item 1: "عند التفعيل يُطلب من
    الأدوار المحددة إعداد 2FA عند أول دخول تالٍ")."""
    if user.totp_confirmed:
        return False
    required_roles = user.tenant.require_2fa_for_roles or []
    if not required_roles:
        return False
    return user.roles.filter(name__in=required_roles).exists()


def record_session(user, refresh_token, request):
    """Sprint 6.6.2 (item 4): a display-only row for "الجلسات النشطة" —
    see apps.accounts.models.UserSession's own docstring for why this
    is separate from simplejwt's OutstandingToken."""
    ip_address = None
    user_agent = ""
    if request is not None:
        ip_address = request.META.get("REMOTE_ADDR")
        user_agent = request.META.get("HTTP_USER_AGENT", "")[:255]
    UserSession.objects.create(
        user=user,
        jti=refresh_token["jti"],
        ip_address=ip_address,
        user_agent=user_agent,
        expires_at=timezone.now() + timedelta(seconds=refresh_token["exp"] - refresh_token["iat"]),
    )


def invalidate_all_sessions(user):
    """Sprint 6.6.2 (item 4): "انتهاء refresh token عند تغيير كلمة
    السر أو تعطيل المستخدم (إبطال كل التوكنات)" + "تسجيل الخروج من كل
    الأجهزة" — both call this. Blacklists every still-outstanding
    refresh token simplejwt issued this user (the real enforcement:
    TokenRefreshView/logout both check the blacklist) and marks every
    UserSession row revoked (the profile screen's own display)."""
    outstanding = OutstandingToken.objects.filter(user_id=user.id)
    BlacklistedToken.objects.bulk_create(
        [BlacklistedToken(token=token) for token in outstanding], ignore_conflicts=True
    )
    UserSession.objects.filter(user=user, revoked_at__isnull=True).update(revoked_at=timezone.now())
