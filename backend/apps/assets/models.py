from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.constants import MONEY_DECIMAL_PLACES, MONEY_MAX_DIGITS
from apps.common.models import TenantScopedModel


class Asset(TenantScopedModel):
    """docs/SYSTEM_ANALYSIS.md 3.3 section 3 + sprint 6.5 (decision 1):
    still a subsidiary register, not a document that posts its own
    purchase entry — the purchase itself is a manual JV/voucher on
    `system_key=FIXED_ASSETS` like any other capital expenditure.
    Depreciation (sprint 6.5) is the first thing that actually posts
    from this model, via `apps.assets.depreciation`."""

    class Category(models.TextChoices):
        VEHICLE = "vehicle", _("Vehicle")
        EQUIPMENT = "equipment", _("Equipment")
        BUILDING = "building", _("Building")
        FURNITURE = "furniture", _("Furniture")
        IT = "it", _("IT")
        OTHER = "other", _("Other")

    class DepreciationMethod(models.TextChoices):
        STRAIGHT_LINE = "straight_line", _("Straight line")
        DECLINING_BALANCE = "declining_balance", _("Declining balance")

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

    # --- Sprint 6.5 (decisions 1, 3, 4, 5, 7, 9): depreciation ---
    is_depreciable = models.BooleanField(_("depreciable"), default=True)
    purchase_reference = models.CharField(_("purchase reference"), max_length=100, blank=True)
    # Decision 4: required to *start* depreciation, not at registration
    # — apps.assets.depreciation.start_depreciation defaults it from
    # purchase_date and freezes it here the first time it runs.
    in_service_date = models.DateField(_("in-service date"), null=True, blank=True)
    # Decision 14: cost/salvage frozen in base currency at the
    # historical purchase_date rate the moment depreciation starts —
    # purchase_cost/salvage_value above stay in the asset's own
    # currency and are never touched again after that freeze.
    cost_base = models.DecimalField(
        _("cost (base currency)"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES,
        null=True, blank=True,
    )
    salvage_base = models.DecimalField(
        _("salvage value (base currency)"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES,
        null=True, blank=True,
    )
    # Decision 9: an asset already in use before this block existed —
    # editable only before start_depreciation runs (then frozen), never
    # touched by any migration or bulk command.
    opening_accumulated_depreciation = models.DecimalField(
        _("opening accumulated depreciation"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES,
        default=0,
    )
    # Decision 5: an annual rate (0 < r < 100), required only with
    # DECLINING_BALANCE — validated in the serializer, not here.
    declining_balance_rate = models.DecimalField(
        _("declining balance rate"), max_digits=5, decimal_places=2, null=True, blank=True,
    )
    # Decision 7: cumulative fraction of the *original* asset disposed
    # of so far (0 = nothing, 1 = fully disposed) — written only by
    # apps.assets.depreciation.dispose_asset, never edited directly.
    disposed_fraction = models.DecimalField(
        _("disposed fraction"), max_digits=5, decimal_places=4, default=0,
    )
    # The current active depreciation schedule, if any — decision 8's
    # transfer relies on updating *this* row's legal_entity/cost_center
    # so not-yet-generated installments pick it up at generation time
    # (RecurringInstallment reads entry.legal_entity/cost_center then,
    # never its own copy — confirmed in apps/accounting/recurring.py).
    depreciation_entry = models.ForeignKey(
        "accounting.RecurringEntry", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="unique_asset_code_per_tenant")
        ]

    def __str__(self):
        return f"{self.code} {self.name}"


class AssetAddition(TenantScopedModel):
    """Sprint 6.5 (decision 6): a capital addition to an existing
    asset — cancels the remaining (DUE) installments of the current
    depreciation schedule and starts a fresh one over (current book
    value + this addition − salvage_base), spread across (remaining
    installments + extend_life_months). Never posts a journal entry
    itself — the purchase is a manual JV/voucher on FIXED_ASSETS like
    any other capital expenditure (decision 1); this row only records
    the schedule recompute apps.assets.depreciation.add_to_asset did."""

    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="additions")
    date = models.DateField(_("date"))
    amount_base = models.DecimalField(
        _("amount (base currency)"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES
    )
    description = models.CharField(_("description"), max_length=255, blank=True)
    extend_life_months = models.PositiveIntegerField(_("extend life (months)"), default=0)
    old_entry = models.ForeignKey("accounting.RecurringEntry", on_delete=models.PROTECT, related_name="+")
    new_entry = models.ForeignKey("accounting.RecurringEntry", on_delete=models.PROTECT, related_name="+")
    created_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.asset.code} +{self.amount_base}"
