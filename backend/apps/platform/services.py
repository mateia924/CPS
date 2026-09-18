import secrets

import pyotp
from django.utils import timezone

from .models import AuditLog, PlatformBackupCode

BACKUP_CODE_COUNT = 10


def generate_totp_secret():
    return pyotp.random_base32()


def totp_provisioning_uri(user, secret):
    return pyotp.totp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="CPS Platform")


def verify_totp(secret, code):
    if not secret or not code:
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def generate_backup_codes(user):
    """Creates BACKUP_CODE_COUNT fresh one-time codes, replacing any
    existing ones. Returns the plaintext codes — the ONLY time they're
    ever available; only sha256 hashes are stored."""
    PlatformBackupCode.objects.filter(user=user).delete()
    raw_codes = [secrets.token_hex(5) for _ in range(BACKUP_CODE_COUNT)]
    PlatformBackupCode.objects.bulk_create(
        [
            PlatformBackupCode(user=user, code_hash=PlatformBackupCode.hash_code(code))
            for code in raw_codes
        ]
    )
    return raw_codes


def consume_backup_code(user, code):
    """Atomically marks a matching, unused backup code as used. Returns
    True if `code` was valid and unused (and is now consumed), False
    otherwise — never usable twice."""
    code_hash = PlatformBackupCode.hash_code(code)
    updated = PlatformBackupCode.objects.filter(
        user=user, code_hash=code_hash, used_at__isnull=True
    ).update(used_at=timezone.now())
    return updated > 0


def log_action(
    actor_type,
    actor_id,
    action,
    target_type="",
    target_id=None,
    tenant_id=None,
    before=None,
    after=None,
    request=None,
):
    """The only way any code in this project writes to AuditLog —
    always an INSERT, never touched again afterwards."""
    ip_address = None
    user_agent = ""
    if request is not None:
        ip_address = request.META.get("REMOTE_ADDR")
        user_agent = request.META.get("HTTP_USER_AGENT", "")[:255]
    AuditLog.objects.create(
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        tenant_id=tenant_id,
        before=before,
        after=after,
        ip_address=ip_address,
        user_agent=user_agent,
    )
