from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.constants import MONEY_DECIMAL_PLACES, MONEY_MAX_DIGITS
from apps.common.models import TenantScopedModel


class Asset(TenantScopedModel):
    """docs/SYSTEM_ANALYSIS.md 3.3 section 3: registration only — no
    depreciation, no journal entries yet (explicitly deferred, see
    Decision Log)."""

    class Category(models.TextChoices):
        VEHICLE = "vehicle", _("Vehicle")
        EQUIPMENT = "equipment", _("Equipment")
        BUILDING = "building", _("Building")
        FURNITURE = "furniture", _("Furniture")
        IT = "it", _("IT")
        OTHER = "other", _("Other")

    class DepreciationMethod(models.TextChoices):
        STRAIGHT_LINE = "straight_line", _("Straight line")

    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        DISPOSED = "disposed", _("Disposed")
        UNDER_MAINTENANCE = "under_maintenance", _("Under maintenance")

    legal_entity = models.ForeignKey(
        "organization.LegalEntity", on_delete=models.PROTECT, related_name="assets"
    )
    code = models.CharField(_("code"), max_length=20)
    name = models.CharField(_("name"), max_length=255)
    category = models.CharField(_("category"), max_length=20, choices=Category.choices)
    purchase_date = models.DateField(_("purchase date"))
    purchase_cost = models.DecimalField(
        _("purchase cost"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES
    )
    currency = models.CharField(_("currency"), max_length=3, default="SAR")
    useful_life_months = models.PositiveIntegerField(_("useful life (months)"), null=True, blank=True)
    salvage_value = models.DecimalField(
        _("salvage value"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, default=0
    )
    depreciation_method = models.CharField(
        _("depreciation method"), max_length=20,
        choices=DepreciationMethod.choices, default=DepreciationMethod.STRAIGHT_LINE,
    )
    custodian = models.ForeignKey(
        "parties.Party", null=True, blank=True, on_delete=models.PROTECT, related_name="custodied_assets"
    )
    cost_center = models.ForeignKey(
        "organization.CostCenter", null=True, blank=True, on_delete=models.PROTECT, related_name="assets"
    )
    status = models.CharField(_("status"), max_length=20, choices=Status.choices, default=Status.ACTIVE)
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="unique_asset_code_per_tenant")
        ]

    def __str__(self):
        return f"{self.code} {self.name}"
