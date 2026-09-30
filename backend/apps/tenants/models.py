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
    # Sprint 6 (block 6.0, item 6 — CFO_REVIEW_1 §7 Q10 gap): set when a
    # Super Admin marks a tenant PAST_DUE (apps.platform.views.
    # TenantAdminViewSet.mark_past_due); a daily beat auto-transitions
    # to SUSPENDED once settings.PAST_DUE_GRACE_DAYS has elapsed.
    past_due_since = models.DateTimeField(_("past due since"), null=True, blank=True)
    # Sprint 6.3 (decision 8): set once every active LegalEntity's
    # INITIAL opening balance is approved — surfaced on the Super Admin
    # tenant list as a "not production-ready" warning, never a hard
    # block (3.16.3: "لا يُعامَل أي مستأجر كعميل إنتاجي... تحمي المنصة
    # قانونيًا" is an operational policy, not a technical gate).
    opening_balances_approved_at = models.DateTimeField(null=True, blank=True)
    # Sprint 6.5.14 (fix: legal_entity_ids[0] was sorted by UUID string,
    # unrelated to entity_type — the same tenant's own documents could
    # land split across its company/branch rows with nothing tying the
    # two together). Nullable: a tenant with no sensible single default
    # (e.g. genuinely multi-branch) simply has none — apps.accounts.
    # views.MeView's own deterministic fallback (BRANCH first, then by
    # name) covers that case, this field is only ever a preference.
    default_legal_entity = models.ForeignKey(
        "organization.LegalEntity", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # Sprint 6.6.2 (item 1): apps.access.Role NAMES (the tenant's own
    # RBAC roles, e.g. "Owner") — a user holding any role named here
    # must set up 2FA on next login (apps.accounts.services.
    # user_requires_2fa_setup). Defaults to [] (off) — the spec's own
    # wording is "عند التفعيل" (once the Owner actively turns this ON
    # from Settings), never a silent default-on for every brand-new
    # tenant; a non-empty default here would force EVERY fresh
    # registration straight into the 2FA setup screen before the Owner
    # ever saw the rest of the product, which is not what "عند
    # التفعيل" describes.
    require_2fa_for_roles = models.JSONField(default=list, blank=True)
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

    class CreditLimitMode(models.TextChoices):
        WARN = "warn", _("Warn")
        BLOCK = "block", _("Block")

    # Sprint 6.8 (F8, decision 16): default WARN — issuing over the
    # customer's credit_limit only warns until a tenant opts into BLOCK.
    credit_limit_mode = models.CharField(
        _("credit limit mode"), max_length=10, choices=CreditLimitMode.choices, default=CreditLimitMode.WARN
    )
    # Sprint 6.8 (D5, decision 19): off by default — no effect on any
    # other tenant until explicitly turned on.
    cost_center_required = models.BooleanField(_("cost center required"), default=False)

    class Meta:
        verbose_name = _("tenant features")
        verbose_name_plural = _("tenant features")

    def __str__(self):
        return f"features for {self.tenant_id}"
