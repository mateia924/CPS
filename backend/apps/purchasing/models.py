from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.constants import (
    MONEY_DECIMAL_PLACES,
    MONEY_MAX_DIGITS,
    PERCENTAGE_DECIMAL_PLACES,
    PERCENTAGE_MAX_DIGITS,
)
from apps.common.models import TenantScopedModel


class PurchaseSettings(models.Model):
    """Sprint 8.0 — one row per tenant, same aux-table shape as
    apps.inventory.models.InventorySettings (plain Model, OneToOneField,
    created lazily by PurchaseSettingsView, never at registration).

    R-8.5: the three-way match tolerance. A bill line whose price
    differs from its receipt by more than BOTH limits needs
    `purchasing.override_match` and a recorded reason (8.5). The
    defaults are S4's proposal (2% / 50 in the base currency), not
    numbers any posting code carries — they live here only.

    `default_grni_policy`: how a bill/receipt price difference settles
    GRNI (8.5). sprint-8.md names the field but defines only one
    behaviour, R-8.1 (binding): to the item's cost for the quantity still
    in stock, the issued part to PURCHASE_PRICE_VARIANCE by ratio. So it
    has one member today; a second is an owner decision, not a guess."""

    class GrniPolicy(models.TextChoices):
        PRORATE_TO_COST_AND_VARIANCE = "prorate", _("Item cost for stock on hand, variance for the issued part")

    tenant = models.OneToOneField(
        "tenants.Tenant", on_delete=models.CASCADE, related_name="purchase_settings"
    )
    match_tolerance_pct = models.DecimalField(
        _("match tolerance (%)"), max_digits=PERCENTAGE_MAX_DIGITS, decimal_places=PERCENTAGE_DECIMAL_PLACES,
        default=Decimal("2.00"),
    )
    match_tolerance_amount = models.DecimalField(
        _("match tolerance (base currency)"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES,
        default=Decimal("50.00"),
    )
    default_grni_policy = models.CharField(
        _("GRNI settlement policy"), max_length=20, choices=GrniPolicy.choices,
        default=GrniPolicy.PRORATE_TO_COST_AND_VARIANCE,
    )

    class Meta:
        verbose_name = _("purchase settings")
        verbose_name_plural = _("purchase settings")

    def __str__(self):
        return f"purchase settings for {self.tenant_id}"


class WithholdingTaxCode(TenantScopedModel):
    """Sprint 8.0 (D6): withholding tax is data per country, never a rate
    in code (sprint-8.md §0 rule 2). Seeded per tenant from
    apps/compliance/<country>/withholding.json by
    apps.purchasing.services.load_withholding_codes — the same per-tenant
    shape as accounting.TaxCode and its tax_codes.json.

    `is_example`: every code loaded from the JSON starts True ("أمثلة —
    راجع استشاريك") and stays True until the owner approves the country's
    table (S2). The loader never touches an existing row, so neither that
    approval nor an edited rate is ever undone by a re-run.

    `base`: what the rate applies to — the line's amount before VAT (NET)
    or including it (GROSS). `applies_to`: which suppliers may carry the
    code (PartyRole.is_resident); 8.3 rejects a mismatch."""

    class Base(models.TextChoices):
        NET = "net", _("Net (before VAT)")
        GROSS = "gross", _("Gross (including VAT)")

    class AppliesTo(models.TextChoices):
        RESIDENT = "resident", _("Resident suppliers")
        NON_RESIDENT = "non_resident", _("Non-resident suppliers")
        BOTH = "both", _("Both")

    country = models.CharField(_("country"), max_length=2)
    code = models.CharField(_("code"), max_length=20)
    name_ar = models.CharField(_("name"), max_length=100)
    rate = models.DecimalField(_("rate (%)"), max_digits=PERCENTAGE_MAX_DIGITS, decimal_places=PERCENTAGE_DECIMAL_PLACES)
    base = models.CharField(_("base"), max_length=10, choices=Base.choices)
    applies_to = models.CharField(_("applies to"), max_length=15, choices=AppliesTo.choices)
    is_example = models.BooleanField(_("example, not yet approved"), default=True)
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["country", "code"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "country", "code"], name="unique_wht_code_per_tenant_country"),
        ]

    def __str__(self):
        return f"{self.country}/{self.code}"
