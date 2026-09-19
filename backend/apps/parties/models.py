import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import TenantScopedModel


class Party(TenantScopedModel):
    """docs/SYSTEM_ANALYSIS.md 3.3: unified "طرف" — one record per real
    counterparty, carrying any number of PartyRole rows (customer,
    supplier, employee, affiliate, bank) instead of a separate table per
    role. Sprint 1's Customer model is superseded by Party+role=CUSTOMER
    (see apps/sales/models.py: Invoice.legacy_customer for the migration
    story) but its table is kept, untouched, forever — no data is ever
    deleted.
    """

    class Type(models.TextChoices):
        INDIVIDUAL = "individual", _("Individual")
        ORGANIZATION = "organization", _("Organization")

    code = models.CharField(_("code"), max_length=20)
    name = models.CharField(_("name"), max_length=255)
    name_en = models.CharField(_("name (English)"), max_length=255, blank=True)
    party_type = models.CharField(
        _("party type"), max_length=20, choices=Type.choices, default=Type.ORGANIZATION
    )
    tax_number = models.CharField(_("tax number"), max_length=50, blank=True)
    national_id_or_cr = models.CharField(_("national ID / commercial registration"), max_length=50, blank=True)
    phone = models.CharField(_("phone"), max_length=50, blank=True)
    email = models.EmailField(_("email"), blank=True)
    address = models.JSONField(_("address"), default=dict, blank=True)
    country_code = models.CharField(_("country code"), max_length=2, default="SA")
    default_currency = models.CharField(_("currency"), max_length=3, default="SAR")
    notes = models.TextField(_("notes"), blank=True)
    is_active = models.BooleanField(_("active"), default=True)

    # Design-only for now (docs/SYSTEM_ANALYSIS.md 3.3/3.4): sprint 3
    # explicitly defers building the full chart-of-accounts tree and
    # auto-created running (جاري) accounts to sprint 4 — "صمّم النماذج
    # بحيث يربطوا بها" — same nullable-for-now pattern as
    # treasury.Bank/CashBox/Custody.gl_account below. Nothing sets this
    # yet.
    gl_account = models.ForeignKey(
        "accounting.Account", null=True, blank=True, on_delete=models.SET_NULL, related_name="parties"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="unique_party_code_per_tenant")
        ]

    def __str__(self):
        return f"{self.code} {self.name}"


class PartyRole(models.Model):
    """A role a Party holds — a party may hold several at once (unique
    per party+role, 3.3: "الطرف الواحد يحمل عدة أدوار ... دون تكرار").
    Not a TenantScopedModel: it belongs to a Party, which already
    carries the tenant."""

    class Role(models.TextChoices):
        CUSTOMER = "customer", _("Customer")
        SUPPLIER = "supplier", _("Supplier")
        EMPLOYEE = "employee", _("Employee")
        AFFILIATE = "affiliate", _("Affiliate company")
        BANK = "bank", _("Bank")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    party = models.ForeignKey(Party, on_delete=models.CASCADE, related_name="roles")
    role = models.CharField(_("role"), max_length=20, choices=Role.choices)
    is_active = models.BooleanField(_("active"), default=True)
    # Role-specific fields (3.3: credit_limit/payment_terms_days for
    # CUSTOMER, payment_terms_days for SUPPLIER, hire_date/job_title for
    # EMPLOYEE) — kept as a flat JSON bag rather than one nullable column
    # per role per field, since each role's fields never overlap and a
    # dedicated column set would mostly be NULL for any given row.
    details = models.JSONField(_("role details"), default=dict, blank=True)
    # AFFILIATE only (3.3: "للشقيقة legal_entity FK للكيان المقابل في
    # الشجرة القانونية") — a real relation, not JSON, since it's an FK.
    legal_entity = models.ForeignKey(
        "organization.LegalEntity", null=True, blank=True, on_delete=models.PROTECT, related_name="affiliate_roles"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["role"]
        constraints = [
            models.UniqueConstraint(fields=["party", "role"], name="unique_role_per_party")
        ]

    def __str__(self):
        return f"{self.party_id} — {self.role}"
