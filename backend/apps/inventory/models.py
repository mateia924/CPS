from django.db import models
from django.utils.translation import gettext_lazy as _


class InventorySettings(models.Model):
    """Sprint 7.0 — one row per tenant, same aux-table shape as
    apps.tenants.models.TenantFeatures (plain Model, OneToOneField,
    never a TenantScopedModel UUID row — there is exactly one of these
    per tenant, never a list a client could create/delete). Every
    field named across sprint-7.md's decisions (D3, D11, D16, D18) is
    collected here up front rather than one migration per decision,
    since the whole set was already known before this model was first
    written — still additive-only from here on, same as every other
    model in this project.

    Created lazily (get_or_create) on first read/write via
    InventorySettingsView, not at tenant registration — same pattern
    apps.numbering.services.get_or_create_numbering_setting already
    uses for DocumentNumberingSetting.
    """

    class Tracking(models.TextChoices):
        NONE = "none", _("None")
        SERIAL = "serial", _("Serial")
        BATCH = "batch", _("Batch")

    tenant = models.OneToOneField(
        "tenants.Tenant", on_delete=models.CASCADE, related_name="inventory_settings"
    )
    # D3 (R-7.2): the owner's own recommendation (S6) is the default —
    # posting a stock document past the available quantity is rejected
    # with 400 unless a tenant explicitly opts into a warning instead.
    allow_negative_stock = models.BooleanField(_("allow negative stock"), default=False)
    # D11: days before a batch's expiry that it starts surfacing in
    # the expiry report / daily email digest.
    expiry_alert_days = models.PositiveIntegerField(_("expiry alert days"), default=30)
    # D16: blocks posting any OTHER stock document against a warehouse
    # while a count session on it is open.
    freeze_warehouse_during_count = models.BooleanField(_("freeze warehouse during count"), default=True)
    # D18: apply_item_feature_defaults' own default for a NEW item
    # category going forward — never retroactively changes an existing
    # category's own already-chosen tracking.
    default_tracking = models.CharField(
        _("default tracking"), max_length=10, choices=Tracking.choices, default=Tracking.NONE
    )
    show_weight_karat_fields = models.BooleanField(_("show weight/karat fields"), default=False)
    units_enabled = models.BooleanField(_("units of measure enabled"), default=False)
    barcode_enabled = models.BooleanField(_("barcode enabled"), default=False)

    class Meta:
        verbose_name = _("inventory settings")
        verbose_name_plural = _("inventory settings")

    def __str__(self):
        return f"inventory settings for {self.tenant_id}"
