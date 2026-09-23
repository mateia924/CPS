import hashlib

import magic
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.utils.translation import gettext_lazy as _

# target_type (API-facing, short and accountant-friendly) -> (app_label,
# model_name) — an explicit whitelist, never a raw ContentType lookup by
# client-supplied app_label/model, so a client can never attach a file
# to an arbitrary internal model (User, Tenant, AuditLog, ...).
ALLOWED_TARGETS = {
    "party": ("parties", "party"),
    "bank": ("treasury", "bank"),
    "cash_box": ("treasury", "cashbox"),
    "custody": ("treasury", "custody"),
    "asset": ("assets", "asset"),
    "invoice": ("sales", "invoice"),
    "journal_entry": ("accounting", "journalentry"),
    "account": ("accounting", "account"),
    "tax_code": ("accounting", "taxcode"),
    "exchange_rate": ("treasury", "exchangerate"),
    # Sprint 5.6 (block 5.6): "الشعار" on the company/legal-entity
    # settings screen reuses AttachmentPanel instead of a dedicated
    # upload widget (same reasoning as 5.2's screen-mounting decision —
    # one mechanism, not a second bespoke one for a single field).
    "legal_entity": ("organization", "legalentity"),
    # Sprint 5.6: voucher detail screens get AttachmentPanel in
    # FINANCIAL mode (receipts/photos of expenses) — not versioned,
    # same treatment as invoice/journal_entry.
    "voucher": ("vouchers", "voucher"),
    # Sprint 5.5 (block 5.5.0): the mandatory IBAN letter attachment
    # (3.17) that submit_iban_change_request checks for before allowing
    # submission for approval.
    "iban_change_request": ("treasury", "ibanchangerequest"),
    # Sprint 5.5 (block 5.5.1): the original imported statement file
    # itself, kept as an audit trail (v2 decision 5).
    "bank_statement": ("treasury", "bankstatement"),
}

# extension -> allowed MIME types (from magic bytes, never trusted from
# the client's Content-Type header or the filename's own extension) —
# rejects e.g. a renamed .exe wearing a ".pdf" filename (5.1 test list).
ALLOWED_EXTENSIONS = {
    "pdf": {"application/pdf"},
    "jpg": {"image/jpeg"},
    "jpeg": {"image/jpeg"},
    "png": {"image/png"},
    "webp": {"image/webp"},
    "xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/zip"},
    "docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/zip"},
    "csv": {"text/csv", "text/plain"},
    # Sprint 5.5 (block 5.5.1): MT940 bank statement exports are plain
    # SWIFT-tag text, commonly shipped with any of these extensions.
    "sta": {"text/plain"},
    "940": {"text/plain"},
    "mt940": {"text/plain"},
    "txt": {"text/plain"},
}

CHUNK_SIZE = 1024 * 1024  # 1 MB


class AttachmentValidationError(ValidationError):
    pass


class LinkInvalid(Exception):
    """Raised by verify_link — expired, tampered, or signed for a
    different attachment than the one requested."""


class StorageQuotaExceeded(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(message)


def resolve_target(tenant, target_type, target_id):
    """Resolves (target_type, target_id) to a real model instance
    belonging to `tenant` — or raises AttachmentValidationError, which
    the view turns into a 404 (never leaking whether the id exists in
    some OTHER tenant — same "404, not 403" rule as every other
    cross-tenant lookup in this project)."""
    mapping = ALLOWED_TARGETS.get(target_type)
    if mapping is None:
        raise AttachmentValidationError({"target_type": [_("Unknown attachment target type.")]})
    app_label, model_name = mapping
    content_type = ContentType.objects.get_by_natural_key(app_label, model_name)
    model = content_type.model_class()
    try:
        instance = model.objects.get(tenant=tenant, id=target_id)
    except model.DoesNotExist:
        raise AttachmentValidationError({"target_id": [_("Target record not found.")]})
    return content_type, instance


def compute_sha256(file_obj):
    """Streams the file to compute its hash without loading it all into
    memory — file_obj must support .chunks() (Django's UploadedFile)."""
    digest = hashlib.sha256()
    for chunk in file_obj.chunks(CHUNK_SIZE):
        digest.update(chunk)
    file_obj.seek(0)
    return digest.hexdigest()


def detect_mime_type(file_obj, original_name):
    """Sniffs real content from the first bytes (python-magic/libmagic)
    — the whole point being that a file's *declared* extension/
    Content-Type can lie, but its magic bytes can't be faked without
    actually being that file type (rule: "من magic bytes لا من
    الامتداد"). Raises AttachmentValidationError if the extension isn't
    in the whitelist, or if the sniffed type doesn't match what that
    extension is allowed to be."""
    ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    allowed_mimes = ALLOWED_EXTENSIONS.get(ext)
    if allowed_mimes is None:
        raise AttachmentValidationError(
            {"file": [_("File type not allowed. Allowed: pdf, jpg, jpeg, png, webp, xlsx, docx, csv.")]}
        )
    head = file_obj.read(2048)
    file_obj.seek(0)
    sniffed = magic.from_buffer(head, mime=True)
    if sniffed not in allowed_mimes:
        raise AttachmentValidationError(
            {"file": [_("The file's actual content does not match its extension (%(ext)s).") % {"ext": ext}]}
        )
    return sniffed


def create_attachment(
    tenant, content_type, target, file_obj, mime_type, sha256, category, user,
    description="", versioned=False, request=None,
):
    """Sprint 5.5 (block 5.5.1): extracted from
    AttachmentViewSet.create (unchanged behavior — same transaction,
    quota increment, scan dispatch, audit log) so a purely internal
    caller (apps.treasury.services.import_bank_statement, attaching the
    original statement file) can create a real Attachment row without
    going through an HTTP request. Callers still run
    check_file_size/check_storage_limit/detect_mime_type/
    compute_sha256 themselves first, same division of labor as before."""
    from django.db import models, transaction

    from apps.platform.models import AuditLog
    from apps.platform.services import log_action

    from .models import Attachment
    from .tasks import scan_attachment

    version, supersedes = 1, None
    if versioned:
        previous = (
            Attachment.objects.filter(
                tenant=tenant, content_type=content_type, object_id=target.id,
                category=category, status=Attachment.Status.ACTIVE,
            )
            .order_by("-version")
            .first()
        )
        if previous is not None:
            version, supersedes = previous.version + 1, previous

    with transaction.atomic():
        attachment = Attachment.objects.create(
            tenant=tenant, content_type=content_type, object_id=target.id,
            file=file_obj, original_name=file_obj.name, mime_type=mime_type,
            size=file_obj.size, sha256=sha256, category=category, description=description,
            uploaded_by=user, upload_ip=request.META.get("REMOTE_ADDR") if request else None,
            version=version, supersedes=supersedes,
        )
        tenant.__class__.objects.filter(id=tenant.id).update(
            storage_used_bytes=models.F("storage_used_bytes") + file_obj.size
        )

    scan_attachment.delay(str(attachment.id))
    attachment.refresh_from_db()

    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER, actor_id=user.id if user else None,
        action="attachment.upload", target_type="attachment", target_id=attachment.id,
        tenant_id=tenant.id,
        after={"original_name": attachment.original_name, "sha256": attachment.sha256, "category": category},
        request=request,
    )
    return attachment


def check_storage_limit(tenant, additional_bytes):
    """Plan.storage_mb (sprint 2 field, applied for real starting here)
    — 413 on the view side, not the generic 402 the other plan-limit
    checks use, since this is specifically "the upload itself is too
    big for what's left", a closer semantic match to 413 Payload Too
    Large than to 402 Payment Required."""
    if tenant.plan is None or tenant.plan.storage_mb is None:
        return
    limit_bytes = tenant.plan.storage_mb * 1024 * 1024
    if tenant.storage_used_bytes + additional_bytes > limit_bytes:
        raise StorageQuotaExceeded(
            _(
                "This upload would exceed your plan's storage limit (%(limit)s MB). "
                "Upgrade your plan or remove old attachments first."
            )
            % {"limit": tenant.plan.storage_mb}
        )


def check_file_size(tenant, size_bytes):
    max_mb = (tenant.plan.max_file_mb if tenant.plan else None) or settings.ATTACHMENT_DEFAULT_MAX_FILE_MB
    if size_bytes > max_mb * 1024 * 1024:
        raise StorageQuotaExceeded(
            _("This file is larger than the maximum allowed size (%(max)s MB) for your plan.")
            % {"max": max_mb}
        )


def _signer():
    return TimestampSigner(key=settings.ATTACHMENT_LINK_SIGNING_KEY, salt="attachments.download")


def sign_link(attachment_id, requested_by_id=None):
    """HMAC-signed (Django's TimestampSigner — HMAC-SHA256 under the
    hood) token embedding the attachment id, who asked for it, and the
    issue time; verify_link checks both the signature and
    ATTACHMENT_LINK_TTL_SECONDS (5 minutes, prompt decision 7) — never a
    permanent link. `requested_by_id` travels inside the token
    specifically so DownloadView (a deliberately unauthenticated
    endpoint — a plain <a href> or a mobile camera upload flow can't
    carry an Authorization header) can still attribute its AuditLog
    DOWNLOAD entry to a real user instead of "unknown"."""
    return _signer().sign_object(
        {"attachment_id": str(attachment_id), "requested_by": str(requested_by_id) if requested_by_id else None}
    )


def verify_link(token, attachment_id):
    """Returns the requested_by id (possibly None) if `token` is a
    valid, unexpired signature for `attachment_id` — or raises
    LinkInvalid otherwise (expired, tampered, or signed for a
    different attachment than the one being requested)."""
    try:
        payload = _signer().unsign_object(token, max_age=settings.ATTACHMENT_LINK_TTL_SECONDS)
    except (BadSignature, SignatureExpired):
        raise LinkInvalid()
    if payload.get("attachment_id") != str(attachment_id):
        raise LinkInvalid()
    return payload.get("requested_by")
