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
