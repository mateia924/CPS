import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class Tenant(models.Model):
    class Status(models.TextChoices):
        TRIAL = "trial", _("Trial")
        ACTIVE = "active", _("Active")
        PAST_DUE = "past_due", _("Past due")
        SUSPENDED = "suspended", _("Suspended")
        ARCHIVED = "archived", _("Archived")

    class BusinessType(models.TextChoices):
        SERVICE = "service", _("Service")
        TRADING = "trading", _("Trading")
        MANUFACTURING = "manufacturing", _("Manufacturing")
        HOLDING = "holding", _("Holding")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_("company name"), max_length=255)
    subdomain = models.SlugField(_("subdomain"), max_length=63, unique=True)
    # Sprint 4.3 (3.4): picked once at registration (basic field, per
    # the sprint spec) — selects which chart-of-accounts template
    # seed_chart_of_accounts applies. Changing it later does not
    # re-template an existing chart (out of scope; a fresh chart is
    # only ever built once, at registration).
    business_type = models.CharField(
        _("business type"), max_length=20, choices=BusinessType.choices, default=BusinessType.SERVICE
    )
    is_active = models.BooleanField(_("active"), default=True)
    # Mandatory per sprint 2, added nullable-then-backfilled-then-NOT-NULL
    # (see apps/tenants/migrations/0004-0006) for tenants that predate it.
    plan = models.ForeignKey("platform.Plan", on_delete=models.PROTECT, related_name="tenants")
    status = models.CharField(_("status"), max_length=20, choices=Status.choices, default=Status.TRIAL)
    trial_ends_at = models.DateTimeField(_("trial ends at"), null=True, blank=True)
    # Sprint 5.1 (3.17): running total of active Attachment.size —
    # incremented on upload, decremented on... never (voided attachments
    # are never deleted — rule 6 legal retention — so their bytes stay
    # counted; only a genuine hard-delete, which this project never does,
    # would free quota). Checked against plan.storage_mb before each
    # upload (apps.attachments.services.check_storage_limit).
    storage_used_bytes = models.BigIntegerField(_("storage used (bytes)"), default=0)
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
    # Sprint 3 (3.3): "Free لا يراها، Business+ يراها" — synced from
    # Plan.feature_treasury/feature_assets the same way as the fields
    # above (see apps/tenants/services.py: apply_plan_to_tenant).
    treasury = models.BooleanField(_("treasury"), default=False)
    assets = models.BooleanField(_("fixed assets"), default=False)

    class Meta:
        verbose_name = _("tenant features")
        verbose_name_plural = _("tenant features")

    def __str__(self):
        return f"features for {self.tenant_id}"
