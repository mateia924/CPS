import hashlib

import clamd
from celery import shared_task
from django.conf import settings
from django.utils import timezone

from .models import Attachment

CHUNK_SIZE = 1024 * 1024


@shared_task
def scan_attachment(attachment_id):
    """3.17 rule 2: async ClamAV scan right after upload — the file is
    not served (see views.DownloadView) until this sets scan_status to
    CLEAN or (dev-only) SKIPPED. ATTACHMENT_SCAN_ENABLED=false marks
    SKIPPED instead of calling clamd at all (dev escape hatch; refused
    at boot in production — see config/settings.py)."""
    try:
        attachment = Attachment.objects.get(id=attachment_id)
    except Attachment.DoesNotExist:
        return

    if not settings.ATTACHMENT_SCAN_ENABLED:
        attachment.scan_status = Attachment.ScanStatus.SKIPPED
        attachment.scanned_at = timezone.now()
        attachment.save(update_fields=["scan_status", "scanned_at"])
        return

    try:
        cd = clamd.ClamdNetworkSocket(host=settings.CLAMD_HOST, port=settings.CLAMD_PORT)
        with attachment.file.open("rb") as f:
            result = cd.instream(f)
        verdict = result.get("stream", (None, None))[0]
        # INFECTED gating: download refuses anything but scan_status in
        # {CLEAN, SKIPPED} (views.DownloadView) — that alone makes the
        # file genuinely inaccessible, without needing a separate
        # physical move to a quarantine/ key (documented simplification
        # — rule 6 forbids deleting the object anyway, and the DB
        # record must stay visible in the attachment list either way
        # so a human notices and re-uploads the correct file).
        attachment.scan_status = (
            Attachment.ScanStatus.INFECTED if verdict == "FOUND" else Attachment.ScanStatus.CLEAN
        )
    except Exception:
        attachment.scan_status = Attachment.ScanStatus.ERROR
    attachment.scanned_at = timezone.now()
    attachment.save(update_fields=["scan_status", "scanned_at"])


@shared_task
def check_attachment_integrity():
    """3.17 rule 2 "فحص دوري يكشف أي تغيير على التخزين" — Celery beat,
    weekly (config/settings.py CELERY_BEAT_SCHEDULE). Re-hashes every
    active attachment and flags a mismatch; does not fix or remove
    anything, purely a detection/reporting task (surfaced today via the
    integrity_status field itself — no Super Admin alert screen exists
    yet, documented debt in README, same as the ClamAV INFECTED
    notification below)."""
    for attachment in Attachment.objects.filter(status=Attachment.Status.ACTIVE):
        digest = hashlib.sha256()
        try:
            with attachment.file.open("rb") as f:
                for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
                    digest.update(chunk)
        except Exception:
            continue
        new_status = (
            Attachment.IntegrityStatus.OK
            if digest.hexdigest() == attachment.sha256
            else Attachment.IntegrityStatus.MISMATCH
        )
        attachment.integrity_status = new_status
        attachment.integrity_checked_at = timezone.now()
        attachment.save(update_fields=["integrity_status", "integrity_checked_at"])
