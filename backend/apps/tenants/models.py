import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class Tenant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_("company name"), max_length=255)
    subdomain = models.SlugField(_("subdomain"), max_length=63, unique=True)
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("tenant")
        verbose_name_plural = _("tenants")

    def __str__(self):
        return self.name


class TenantFeatures(models.Model):
    """Feature flags per tenant (3.13). Sprint 2 will wire this up to
    packages; for now it's just a table, defaulting to whatever this
    sprint actually built enabled and everything else off."""

    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name="features")
    organization = models.BooleanField(_("organization structure"), default=True)
    cost_centers = models.BooleanField(_("cost centers"), default=True)
    inventory = models.BooleanField(_("inventory"), default=False)
    purchasing = models.BooleanField(_("purchasing"), default=False)
    hr = models.BooleanField(_("HR"), default=False)

    class Meta:
        verbose_name = _("tenant features")
        verbose_name_plural = _("tenant features")

    def __str__(self):
        return f"features for {self.tenant_id}"
