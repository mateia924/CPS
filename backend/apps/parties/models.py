import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.constants import MONEY_DECIMAL_PLACES, MONEY_MAX_DIGITS
from apps.common.models import SoftDeleteModelMixin, StructuredAddressMixin, TenantScopedModel


class Party(TenantScopedModel, StructuredAddressMixin, SoftDeleteModelMixin):
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
    # Sprint 6.8 (F17, decision 20): StructuredAddressMixin (building_
    # number/street/district/city/postal_code/short_address) — for
    # e-invoicing later; the free-text `address` above is untouched.
    country_code = models.CharField(_("country code"), max_length=2, default="SA")
    default_currency = models.CharField(_("currency"), max_length=3, default="SAR")
    notes = models.TextField(_("notes"), blank=True)
    is_active = models.BooleanField(_("active"), default=True)

    # Sprint 3: designed nullable-for-now, meant to be set in sprint 4.
    # SUPERSEDED by accounting.Account.party (sprint 4.3) — a single FK
    # here can't represent "one party, two roles, two accounts"
    # (customer + supplier), which 3.4 explicitly requires. Kept,
    # untouched, unused going forward — see the Decision Log, same
    # never-delete pattern as Invoice.legacy_customer.
    gl_account = models.ForeignKey(
        "accounting.Account", null=True, blank=True, on_delete=models.SET_NULL, related_name="parties"
    )

    # Sprint 5.5 (block 5.5.0, CFO_REVIEW_1 C10): a real column,
    # superseding the free-text `PartyRole.details["iban"]` a supplier
    # role could hold since sprint 3.5 (see SupplierPartySerializer —
    # that key is now a dead, never-read-or-written historical
    # leftover, backfilled into this column once by
    # 0002_backfill_party_iban_from_role_details.py and never touched
    # again). First entry (empty -> value) is free; any change to a
    # non-empty value must go through treasury.IbanChangeRequest — see
    # that model's docstring.
    iban = models.CharField(_("IBAN"), max_length=34, blank=True)

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
    # Sprint 6.8 (F8, decision 16): promoted out of `details["credit_limit"]`
    # into a real column, same "IBAN precedent" as Party.iban (5.5.0) —
    # `details["credit_limit"]` stays a dead historical key, never read
    # again after the backfill migration. Meaningful for CUSTOMER only;
    # null = unlimited (no check performed at all).
    credit_limit = models.DecimalField(
        _("credit limit"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, null=True, blank=True
    )
    # AFFILIATE (3.3: "للشقيقة legal_entity FK للكيان المقابل في الشجرة
    # القانونية") — a real relation, not JSON, since it's an FK. Sprint
    # 3.5 (v1.4 3.3 field table) reuses this same nullable column for
    # EMPLOYEE too ("الفرع" — which branch the employee works at):
    # deliberate reuse of an existing generic column rather than adding a
    # second one, since sprint 3.5 is explicitly a no-schema-change UI
    # sprint. Meaningless for CUSTOMER/SUPPLIER/BANK roles — always null.
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
