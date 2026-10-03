from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from storages.backends.s3boto3 import S3Boto3Storage


class AttachmentStorage(S3Boto3Storage):
    """S3-compatible storage for Attachment.file only — never Django's
    global DEFAULT_FILE_STORAGE, so nothing else in the project is
    affected. Points at MinIO today (docker-compose.yml); switching to
    OCI Object Storage in production later (prompt decision 7) is an
    env-only change (endpoint/keys), not a code change — OCI's S3-
    compatibility API works with the same boto3 client this class uses.

    querystring_auth=False: this project never hands out S3/MinIO's own
    presigned URLs directly (decision 7: "presigned مباشر من S3 = تحسين
    لاحق، دين موثّق") — every download goes through Django's own
    HMAC-signed /link/ + /download/ pair instead, so scan_status and
    tenant/permission checks are always enforced before a byte is
    served, which a raw S3 presigned URL could never do.
    """

    bucket_name = settings.MINIO_BUCKET
    endpoint_url = settings.MINIO_ENDPOINT_URL
    access_key = settings.MINIO_ACCESS_KEY
    secret_key = settings.MINIO_SECRET_KEY
    addressing_style = "path"
    default_acl = None
    querystring_auth = False
    file_overwrite = False
    region_name = "us-east-1"  # ignored by MinIO; boto3 requires some value


def attachment_storage():
    """Sprint 7.0 (CI #56/#61): a plain callable, not a module-level
    instance — Django's FileField has accepted a callable `storage=`
    since 4.2 specifically so this can be evaluated lazily, after
    settings are configured, instead of at import time. CI sets
    ATTACHMENT_STORAGE_BACKEND=local (no MinIO service there at all —
    see config/settings.py's own note); every other environment
    (dev/staging/production) keeps the real S3-compatible backend
    unchanged. Every attachment test goes through Django's ordinary
    File API (attachment.file.open/.read) regardless of which backend
    is active — nothing in this project's own code is storage-aware
    beyond this one function."""
    if settings.ATTACHMENT_STORAGE_BACKEND == "local":
        root = Path("/tmp/cps-ci-attachments")
        root.mkdir(parents=True, exist_ok=True)
        return FileSystemStorage(location=str(root))
    return AttachmentStorage()
