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
