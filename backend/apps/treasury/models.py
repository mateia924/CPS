from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import TenantScopedModel


class Bank(TenantScopedModel):
    """docs/SYSTEM_ANALYSIS.md 3.3 section 2: registration only, no
    movements yet — `gl_account` is nullable-for-now, filled in
    automatically starting sprint 4 (same pattern as Party.gl_account)."""

    legal_entity = models.ForeignKey(
        "organization.LegalEntity", on_delete=models.PROTECT, related_name="banks"
    )
    name = models.CharField(_("name"), max_length=255)
    bank_name = models.CharField(_("bank name"), max_length=255, blank=True)
    account_number = models.CharField(_("account number"), max_length=64, blank=True)
    iban = models.CharField(_("IBAN"), max_length=34, blank=True)
    swift = models.CharField(_("SWIFT"), max_length=11, blank=True)
    currency = models.CharField(_("currency"), max_length=3, default="SAR")
    gl_account = models.ForeignKey(
        "accounting.Account", null=True, blank=True, on_delete=models.SET_NULL, related_name="banks"
    )
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class CashBox(TenantScopedModel):
    legal_entity = models.ForeignKey(
        "organization.LegalEntity", on_delete=models.PROTECT, related_name="cash_boxes"
    )
    name = models.CharField(_("name"), max_length=255)
    currency = models.CharField(_("currency"), max_length=3, default="SAR")
    # Optional (3.3 section 2) — an employee Party responsible for this
    # cash box. Validated in the serializer to actually hold the
    # EMPLOYEE role, not just be any party.
    custodian = models.ForeignKey(
        "parties.Party", null=True, blank=True, on_delete=models.PROTECT, related_name="cash_boxes"
    )
    gl_account = models.ForeignKey(
        "accounting.Account", null=True, blank=True, on_delete=models.SET_NULL, related_name="cash_boxes"
    )
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "cash boxes"

    def __str__(self):
        return self.name


class Custody(TenantScopedModel):
    """عهدة: cash advanced to a specific employee — unlike CashBox, the
    employee link is mandatory (3.3 section 2)."""

    legal_entity = models.ForeignKey(
        "organization.LegalEntity", on_delete=models.PROTECT, related_name="custodies"
    )
    employee = models.ForeignKey(
        "parties.Party", on_delete=models.PROTECT, related_name="custodies"
    )
    name = models.CharField(_("name"), max_length=255)
    currency = models.CharField(_("currency"), max_length=3, default="SAR")
    gl_account = models.ForeignKey(
        "accounting.Account", null=True, blank=True, on_delete=models.SET_NULL, related_name="custodies"
    )
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "custodies"

    def __str__(self):
        return self.name
