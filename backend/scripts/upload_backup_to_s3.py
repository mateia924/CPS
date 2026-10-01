"""Sprint 6.6.4 ("Option 1", sprint-6.6.md v1.1 §6.1): uploads one
already-encrypted backup file to an S3-compatible bucket — OCI Object
Storage once the owner delivers real credentials (M3), MinIO (already
running, already has real credentials in every environment) as the
INTERIM target until then, chosen by scripts/backup.sh's own caller
logic (this script itself is endpoint-agnostic; it just uses whatever
CPS_UPLOAD_* env vars it's given). Invoked by scripts/backup.sh via
`docker compose exec backend python3 /app/scripts/
upload_backup_to_s3.py`, never run directly. Reuses boto3 (already a
dependency for apps.attachments' own MinIO/S3 storage) instead of
adding a new host package (aws-cli/mc/rclone) just for this one step.

MinIO-as-interim-target needs its own bucket to exist first (OCI's
real bucket is the owner's own, already provisioned by them as part of
M3) — `create_bucket` is idempotent-by-catch here (BucketAlreadyOwnedByYou/
BucketAlreadyExists both mean "already fine", not a real failure).

All configuration arrives via env vars backup.sh passes on the `exec`
call itself (CPS_UPLOAD_*) — never apps.settings — since this script
has nothing to do with the running Django application and must stay
usable even if settings.py's own required values are missing or wrong.
"""

import os
import sys

import boto3
from botocore.exceptions import BotoCoreError, ClientError


def main():
    bucket = os.environ["CPS_UPLOAD_BUCKET"]
    file_path = os.environ["CPS_UPLOAD_FILE"]
    key = os.path.basename(file_path)

    client = boto3.client(
        "s3",
        endpoint_url=os.environ["CPS_UPLOAD_ENDPOINT_URL"],
        aws_access_key_id=os.environ["CPS_UPLOAD_ACCESS_KEY"],
        aws_secret_access_key=os.environ["CPS_UPLOAD_SECRET_KEY"],
        region_name=os.environ.get("CPS_UPLOAD_REGION", "us-ashburn-1"),
    )
    if os.environ.get("CPS_UPLOAD_ENSURE_BUCKET") == "1":
        try:
            client.create_bucket(Bucket=bucket)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                print(f"upload_backup_to_s3: FAILED ensuring bucket {bucket} exists: {exc}", file=sys.stderr)
                sys.exit(1)

    try:
        client.upload_file(file_path, bucket, key)
    except (BotoCoreError, ClientError) as exc:
        print(f"upload_backup_to_s3: FAILED uploading {key} to {bucket}: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"upload_backup_to_s3: uploaded {key} to s3://{bucket}/{key}")


if __name__ == "__main__":
    main()
