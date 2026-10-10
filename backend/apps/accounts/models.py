import hashlib
import uuid

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils.translation import gettext_lazy as _

from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        OWNER = "owner", _("Owner")
        ADMIN = "admin", _("Admin")
        STAFF = "staff", _("Staff")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.CASCADE, related_name="users"
    )
    email = models.EmailField(_("email address"))
    first_name = models.CharField(_("first name"), max_length=150, blank=True)
    last_name = models.CharField(_("last name"), max_length=150, blank=True)
    role = models.CharField(
        _("role"), max_length=20, choices=Role.choices, default=Role.STAFF
    )
    is_active = models.BooleanField(_("active"), default=True)
    is_staff = models.BooleanField(_("staff status"), default=False)
    date_joined = models.DateTimeField(_("date joined"), auto_now_add=True)
    # Sprint 6.8 (decision 17): default True — the daily digest opts
    # every user in; this is the per-user off switch.
    notify_approvals_email = models.BooleanField(_("notify approvals by email"), default=True)

    # Sprint 6.6.2 (item 2): forced on creation via "مستخدم جديد" or
    # reset via "تعديل" — apps.accounts.middleware.MustChangePassword
    # Middleware blocks every API call except the change-password
    # screen itself while this is True.
    must_change_password = models.BooleanField(_("must change password"), default=False)

    # Sprint 6.6.2 (item 1): 2FA (TOTP) — same mechanism as
    # apps.platform.models.PlatformUser (apps.platform.services'
    # generate_totp_secret/verify_totp are reused as-is, not copied),
    # but opt-in per tenant user rather than mandatory. A tenant's
    # `require_2fa_for_roles` only forces *enrollment* on next login
    # (apps.accounts.services.user_requires_2fa) — the actual
    # code-at-login gate is `totp_confirmed`, so a user who opted in
    # voluntarily is gated the same way as one whose role required it.
    totp_secret = models.CharField(max_length=64, blank=True)
    totp_confirmed = models.BooleanField(default=False)

    # RBAC (sprint 1, docs/SYSTEM_ANALYSIS.md 3.14). Independent of the
    # legacy `role` field above (kept as-is from Sprint 0 for is_staff/
    # admin-site bypass purposes) — "owner" in the RBAC sense means
    # holding the tenant's system Owner Role via this M2M, checked by
    # apps.access.services.user_is_owner(), not by `role == OWNER`.
    roles = models.ManyToManyField("access.Role", related_name="users", blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "email"], name="unique_email_per_tenant"
            )
        ]

    def __str__(self):
        return f"{self.email} ({self.tenant_id})"

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip() or self.email

    def get_short_name(self):
        return self.first_name or self.email


class BackupCode(models.Model):
    """Sprint 6.6.2 (item 1): tenant-user equivalent of
    apps.platform.models.PlatformBackupCode — same shape (hashed,
    one-time), separate table since a tenant User and a PlatformUser
    are unrelated models."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="backup_codes")
    code_hash = models.CharField(max_length=64)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "code_hash"], name="unique_tenant_backup_code_per_user")
        ]

    @staticmethod
    def hash_code(raw_code):
        return hashlib.sha256(raw_code.encode()).hexdigest()

    def __str__(self):
        return f"backup code for {self.user_id} ({'used' if self.used_at else 'unused'})"


class UserSession(models.Model):
    """Sprint 6.6.2 (item 4): display-only record of a login's refresh
    token — simplejwt's own OutstandingToken/BlacklistedToken (already
    installed, token_blacklist app) carry no device/IP metadata and stay
    the actual ENFORCEMENT mechanism (apps.accounts.services.
    invalidate_all_sessions blacklists them); this table only backs the
    "الجلسات النشطة" list in the profile screen. `jti` links the two —
    the refresh token's own JWT ID claim, same value OutstandingToken
    rows are keyed by."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sessions")
    jti = models.CharField(max_length=255, unique=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"session {self.jti} for {self.user_id}"


class PasswordResetToken(models.Model):
    """Sprint 7.2.9 (§8.9, R-7.2.9.2): self-service "forgot password"
    for a user who CANNOT log in — distinct from ChangePasswordView
    (already-authenticated self-service) and apps.access.views'
    reset_password (admin picks the value, forbidden for this flow by
    owner decision). Same hashed-not-plaintext principle as
    BackupCode.code_hash above: a database leak must not hand out a
    usable credential. `tenant` is denormalized from `user.tenant` at
    creation time (not derived at check time) specifically so a
    confirm request scoped to the WRONG tenant's subdomain can be
    rejected by a plain field comparison, with no risk of a stale
    `user.tenant_id` read racing a tenant transfer that doesn't exist
    in this codebase anyway — explicit beats implicit here."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="password_reset_tokens")
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="+")
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    @staticmethod
    def hash_token(raw_token):
        return hashlib.sha256(raw_token.encode()).hexdigest()

    def __str__(self):
        return f"password reset token for {self.user_id} ({'used' if self.used_at else 'unused'})"
