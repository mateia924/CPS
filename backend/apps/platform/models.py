import hashlib
import uuid

from django.contrib.auth.models import AbstractBaseUser
from django.db import models
from django.utils.translation import gettext_lazy as _

from .managers import PlatformUserManager


class PlatformUser(AbstractBaseUser):
    """docs/SYSTEM_ANALYSIS.md 3.14: entirely separate from
    accounts.User — own table, no tenant, no relation to tenant users.
    Deliberately does NOT use PermissionsMixin/is_superuser/Django
    groups — role is the single coarse-grained field platform code
    checks (apps.platform.permissions), keeping this model minimal and
    not accidentally wired into django.contrib.auth's permission system
    (which assumes AUTH_USER_MODEL, and this isn't it).
    """

    class Role(models.TextChoices):
        SUPER_ADMIN = "super_admin", _("Super Admin")
        SUPPORT = "support", _("Support")
        BILLING = "billing", _("Billing")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(_("email"), unique=True)
    full_name = models.CharField(_("full name"), max_length=255)
    role = models.CharField(_("role"), max_length=20, choices=Role.choices, default=Role.SUPPORT)
    is_active = models.BooleanField(_("active"), default=True)
    date_joined = models.DateTimeField(_("date joined"), auto_now_add=True)

    # 2FA (mandatory — see apps/platform/services.py and the
    # create_platform_user management command, the only way to create a
    # PlatformUser; it forces TOTP enrollment + backup codes before the
    # account is usable, so totp_confirmed is always True by the time any
    # web login is attempted).
    totp_secret = models.CharField(max_length=64, blank=True)
    totp_confirmed = models.BooleanField(default=False)

    objects = PlatformUserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = _("platform user")
        verbose_name_plural = _("platform users")

    def __str__(self):
        return self.email


class PlatformBackupCode(models.Model):
    """One-time 2FA recovery codes. Stored hashed (sha256) — never
    plaintext; a code is shown to the operator exactly once, at
    creation time, in the management command's terminal output."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(PlatformUser, on_delete=models.CASCADE, related_name="backup_codes")
    code_hash = models.CharField(max_length=64)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "code_hash"], name="unique_backup_code_per_user")
        ]

    @staticmethod
    def hash_code(raw_code):
        return hashlib.sha256(raw_code.encode()).hexdigest()

    def __str__(self):
        return f"backup code for {self.user_id} ({'used' if self.used_at else 'unused'})"


class Plan(models.Model):
    """docs/SYSTEM_ANALYSIS.md 3.14 sprint 2 spec: limits + the same
    feature-flag keys as tenants.TenantFeatures (3.13). null limit =
    unlimited."""

    code = models.SlugField(_("code"), unique=True)
    name = models.CharField(_("name"), max_length=100)
    is_active = models.BooleanField(_("active"), default=True)

    max_users = models.PositiveIntegerField(_("max users"), null=True, blank=True)
    max_branches = models.PositiveIntegerField(_("max branches"), null=True, blank=True)
    max_invoices_per_month = models.PositiveIntegerField(
        _("max invoices per month"), null=True, blank=True
    )
    storage_mb = models.PositiveIntegerField(_("storage (MB)"), null=True, blank=True)

    feature_organization = models.BooleanField(_("organization structure"), default=False)
    feature_cost_centers = models.BooleanField(_("cost centers"), default=False)
    feature_inventory = models.BooleanField(_("inventory"), default=False)
    feature_purchasing = models.BooleanField(_("purchasing"), default=False)
    feature_hr = models.BooleanField(_("HR"), default=False)
    feature_treasury = models.BooleanField(_("treasury"), default=False)
    feature_assets = models.BooleanField(_("fixed assets"), default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return self.name


class AuditLog(models.Model):
    """docs/SYSTEM_ANALYSIS.md 3.14: append-only. No view in this
    codebase ever issues UPDATE/DELETE against this table — enforced
    doubly, at the DRF layer (ReadOnlyModelViewSet only) and at the
    database layer via a BEFORE UPDATE OR DELETE trigger installed by
    platform/migrations/0003_restrict_auditlog_db_permissions.py (see
    that file's docstring for why a trigger was used instead of a plain
    REVOKE)."""

    class ActorType(models.TextChoices):
        PLATFORM = "platform", _("Platform")
        TENANT_USER = "tenant_user", _("Tenant user")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor_type = models.CharField(max_length=20, choices=ActorType.choices)
    actor_id = models.UUIDField(null=True, blank=True)
    action = models.CharField(max_length=100)
    target_type = models.CharField(max_length=100, blank=True)
    target_id = models.UUIDField(null=True, blank=True)
    tenant_id = models.UUIDField(null=True, blank=True)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.actor_type}:{self.actor_id} {self.action}"
