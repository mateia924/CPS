import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import SoftDeleteModelMixin, TenantScopedModel


class Permission(models.Model):
    """Global, tenant-independent catalog of permission codes in
    "<module>.<action>" form (3.14 / sprint 1 spec). Seeded once via a
    data migration — never created through the API."""

    code = models.CharField(_("code"), max_length=100, primary_key=True)
    description = models.CharField(_("description"), max_length=255, blank=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return self.code


class Role(TenantScopedModel, SoftDeleteModelMixin):
    """Tenant-scoped so each tenant's copy of a system role (Owner,
    Accountant, Sales, Viewer) can be edited independently without
    affecting other tenants — "أدوار نظامية ... قابلة للتعديل"."""

    name = models.CharField(_("name"), max_length=100)
    is_system = models.BooleanField(_("system role"), default=False)
    permissions = models.ManyToManyField(Permission, related_name="roles", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "name"], name="unique_role_name_per_tenant")
        ]

    def __str__(self):
        return f"{self.name} ({self.tenant_id})"


class UserEntityAccess(models.Model):
    """Which legal entities a user may see (3.14). Access to a node
    implies access to its descendants — see
    organization.services.get_accessible_entity_ids. Irrelevant for a
    user holding the system Owner role, who always sees everything."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="entity_access"
    )
    legal_entity = models.ForeignKey(
        "organization.LegalEntity", on_delete=models.CASCADE, related_name="user_access"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "legal_entity"], name="unique_user_entity_access"
            )
        ]

    def __str__(self):
        return f"{self.user_id} -> {self.legal_entity_id}"
