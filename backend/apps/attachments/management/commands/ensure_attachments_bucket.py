import boto3
from botocore.exceptions import ClientError
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    """Sprint 5.1 (3.17): "bucket خاص يُنشأ عند الإقلاع (أمر إداري
    idempotent)" — run on every backend container start
    (docker-compose.yml), creates the bucket only if it doesn't already
    exist. Safe to run any number of times."""

    help = "Create the attachments bucket in MinIO/S3 if it doesn't already exist."

    def handle(self, *args, **options):
        # Sprint 7.0 (CI #61): nothing to create when storage is local
        # (CI's e2e job, docker-compose.ci.yml — see apps.attachments.
        # storage.attachment_storage) — this command's whole purpose is
        # S3-bucket provisioning, so it's a correct no-op here, not a
        # special case bolted on.
        if settings.ATTACHMENT_STORAGE_BACKEND == "local":
            self.stdout.write("ATTACHMENT_STORAGE_BACKEND=local — no bucket to ensure.")
            return
        client = boto3.client(
            "s3",
            endpoint_url=settings.MINIO_ENDPOINT_URL,
            aws_access_key_id=settings.MINIO_ACCESS_KEY,
            aws_secret_access_key=settings.MINIO_SECRET_KEY,
        )
        bucket = settings.MINIO_BUCKET
        try:
            client.head_bucket(Bucket=bucket)
            self.stdout.write(f"Bucket '{bucket}' already exists.")
        except ClientError:
            client.create_bucket(Bucket=bucket)
            self.stdout.write(self.style.SUCCESS(f"Created bucket '{bucket}'."))
