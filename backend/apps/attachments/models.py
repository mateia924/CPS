import uuid

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.common.constants import MONEY_DECIMAL_PLACES, MONEY_MAX_DIGITS
from apps.common.models import TenantScopedModel

from .storage import AttachmentStorage


def attachment_upload_path(instance, filename):
    """{tenant_id}/{entity_type}/{year}/{uuid}.{ext} (3.17) — the
    filename on disk/in the bucket is never the original name (avoids
    collisions and leaking the original name into a public-ish path);
    original_name is kept as its own column for display/download."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    entity_type = instance.content_type.model if instance.content_type_id else "unknown"
    year = timezone.localdate().year
    return f"{instance.tenant_id}/{entity_type}/{year}/{uuid.uuid4()}.{ext}"


class Attachment(TenantScopedModel):
    """docs/SYSTEM_ANALYSIS.md 3.17 — the single Attachment model behind
    every detail screen's AttachmentPanel (5.2), whatever it's attached
    to (GenericFK: content_type + object_id, resolved only within the
    caller's own tenant — see apps.attachments.services.resolve_target).
    """

    class Category(models.TextChoices):
        FATURA_ORIGINAL = "fatura_original", _("Original supplier invoice")
        RECEIPT = "receipt", _("Receipt")
        CONTRACT = "contract", _("Contract")
        BANK_LETTER = "bank_letter", _("Bank letter")
        ID_DOCUMENT = "id_document", _("ID document")
        APPROVAL_MINUTES = "approval_minutes", _("Approval minutes")
        OTHER = "other", _("Other")

    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        VOIDED = "voided", _("Voided")

    class ScanStatus(models.TextChoices):
        PENDING = "pending", _("Pending")
        CLEAN = "clean", _("Clean")
        INFECTED = "infected", _("Infected")
        ERROR = "error", _("Error")
        SKIPPED = "skipped", _("Skipped (scanning disabled)")

    class IntegrityStatus(models.TextChoices):
        UNCHECKED = "unchecked", _("Unchecked")
        OK = "ok", _("OK")
        MISMATCH = "mismatch", _("Mismatch")

    # GenericFK target — never trusted from the client without resolving
    # it inside the caller's own tenant first (rule 1: tenant isolation).
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="+")
    object_id = models.UUIDField()
    target = GenericForeignKey("content_type", "object_id")

    file = models.FileField(_("file"), upload_to=attachment_upload_path, storage=AttachmentStorage())
    original_name = models.CharField(_("original file name"), max_length=255)
    # Sniffed from magic bytes (services.detect_mime_type), never trusted
    # from the client's Content-Type header or file extension alone.
    mime_type = models.CharField(_("MIME type"), max_length=100)
    size = models.BigIntegerField(_("size (bytes)"))
    sha256 = models.CharField(_("SHA-256"), max_length=64)

    category = models.CharField(_("category"), max_length=20, choices=Category.choices)
    description = models.CharField(_("description"), max_length=255, blank=True)

    uploaded_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    uploaded_at = models.DateTimeField(_("uploaded at"), auto_now_add=True)
    upload_ip = models.GenericIPAddressField(_("upload IP"), null=True, blank=True)

    status = models.CharField(_("status"), max_length=10, choices=Status.choices, default=Status.ACTIVE)
    void_reason = models.CharField(_("void reason"), max_length=255, blank=True)
    voided_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    voided_at = models.DateTimeField(_("voided at"), null=True, blank=True)

    # Master-data/settings screens: a new upload of the same category
    # creates version N+1 and points back at the one it replaces — both
    # rows are kept forever (rule 6, legal retention), never deleted.
    version = models.PositiveIntegerField(_("version"), default=1)
    supersedes = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="superseded_by"
    )

    scan_status = models.CharField(
        _("scan status"), max_length=10, choices=ScanStatus.choices, default=ScanStatus.PENDING
    )
    scanned_at = models.DateTimeField(_("scanned at"), null=True, blank=True)

    integrity_status = models.CharField(
        _("integrity status"), max_length=10, choices=IntegrityStatus.choices,
        default=IntegrityStatus.UNCHECKED,
    )
    integrity_checked_at = models.DateTimeField(_("integrity checked at"), null=True, blank=True)

    # OCR (deferred — 3.17): columns ready, nothing populates them yet.
    extracted_amount = models.DecimalField(
        _("extracted amount"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES,
        null=True, blank=True,
    )
    extracted_date = models.DateField(_("extracted date"), null=True, blank=True)
    extracted_ref = models.CharField(_("extracted reference"), max_length=100, blank=True)

    class Meta:
        ordering = ["-uploaded_at"]
        indexes = [
            models.Index(fields=["tenant", "content_type", "object_id"]),
        ]

    def __str__(self):
        return f"{self.original_name} ({self.category})"
