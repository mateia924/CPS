import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class TenantScopedModel(models.Model):
    """Base for every business table: always carries the owning tenant.

    Never expose `tenant` as a writable API field — it is always set
    server-side from request.user.tenant. See apps/common/viewsets.py.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.CASCADE, related_name="%(class)ss"
    )

    class Meta:
        abstract = True


class DocumentStateMixin(models.Model):
    """Sprint 4.4 (docs/SYSTEM_ANALYSIS.md 3.15.1): the unified
    financial-document status vocabulary — first used by JournalEntry
    (this sprint), reused by Invoice in sprint 4.5 and by vouchers in
    sprint 5. Only the field/vocabulary is shared; each concrete model
    still defines its own legal transitions (what's allowed from what
    state) and actions, since those differ per document type.

    "REVERSED" is a terminal marker, not an exclusion: a reversed
    entry's lines really were posted and stay in every balance/report
    query (rule 13 reads "POSTED or REVERSED" together) — the
    offsetting reversal entry (its own, separate, POSTED row) is what
    actually zeroes the net effect out. See
    apps.accounting.services.REPORTABLE_STATUSES.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        PENDING_APPROVAL = "pending_approval", _("Pending approval")
        APPROVED = "approved", _("Approved")
        POSTED = "posted", _("Posted")
        REVERSED = "reversed", _("Reversed")

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)

    class Meta:
        abstract = True


class StructuredAddressMixin(models.Model):
    """Sprint 5.6 (block 5.6): the Saudi-format structured address
    (building number, street, district, city, postal code, short
    address) — first built directly on LegalEntity, extracted here in
    sprint 6.8 (F17, decision 20) so Party can share the exact same
    fields instead of a second, drifting copy. All optional — a legacy
    free-text `address` field (Party's own) is untouched by this."""

    building_number = models.CharField(_("building number"), max_length=20, blank=True)
    street = models.CharField(_("street"), max_length=255, blank=True)
    district = models.CharField(_("district"), max_length=255, blank=True)
    city = models.CharField(_("city"), max_length=255, blank=True)
    postal_code = models.CharField(_("postal code"), max_length=10, blank=True)
    short_address = models.CharField(_("short address"), max_length=10, blank=True)

    class Meta:
        abstract = True
