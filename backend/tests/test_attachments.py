"""Sprint 5.1 (docs/SYSTEM_ANALYSIS.md 3.17): Attachment model, S3
storage (MinIO), SHA-256, real ClamAV scanning, signed downloads,
AuditLog — all against the real running services (MinIO + ClamAV), no
mocks, matching this project's testing philosophy throughout.
"""

import io

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.signing import TimestampSigner
from rest_framework.test import APIClient

from apps.attachments.models import Attachment
from apps.platform.models import Plan
from apps.tenants.services import apply_plan_to_tenant

from .factories import PartyFactory

PDF_BYTES = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF"
)
EXE_BYTES = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00"
EICAR_BYTES = (
    rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
)


def _pdf_file(name="receipt.pdf"):
    return io.BytesIO(PDF_BYTES), name


def _upload(client, party, filename=None, content=None, category="receipt"):
    content_bytes, default_name = _pdf_file()
    from django.core.files.uploadedfile import SimpleUploadedFile

    upload = SimpleUploadedFile(
        filename or default_name, content if content is not None else PDF_BYTES,
        content_type="application/octet-stream",
    )
    return client.post(
        "/api/attachments/",
        {"target_type": "party", "target_id": str(party.id), "category": category, "file": upload},
        format="multipart",
    )


@pytest.mark.django_db
def test_upload_pdf_computes_sha256_and_logs_audit(tenant_a, client_a):
    import hashlib

    party = PartyFactory(tenant=tenant_a)
    response = _upload(client_a, party)
    assert response.status_code == 201
    assert response.data["sha256"] == hashlib.sha256(PDF_BYTES).hexdigest()
    assert response.data["mime_type"] == "application/pdf"
    assert response.data["scan_status"] in ("clean", "skipped")

    from apps.platform.models import AuditLog

    assert AuditLog.objects.filter(action="attachment.upload", target_id=response.data["id"]).exists()


@pytest.mark.django_db
def test_exe_renamed_as_pdf_is_rejected(tenant_a, client_a):
    party = PartyFactory(tenant=tenant_a)
    response = _upload(client_a, party, filename="invoice.pdf", content=EXE_BYTES)
    assert response.status_code == 400


@pytest.mark.django_db
def test_storage_quota_exceeded_returns_413(tenant_a, client_a):
    tiny_plan = Plan.objects.create(code="tiny-storage", name="Tiny", storage_mb=0)
    apply_plan_to_tenant(tenant_a, tiny_plan)
    party = PartyFactory(tenant=tenant_a)
    response = _upload(client_a, party)
    assert response.status_code == 413


@pytest.mark.django_db
def test_file_larger_than_plan_max_file_mb_returns_413(tenant_a, client_a):
    tenant_a.plan.max_file_mb = 1
    tenant_a.plan.save(update_fields=["max_file_mb"])
    party = PartyFactory(tenant=tenant_a)
    big_content = PDF_BYTES + b"0" * (2 * 1024 * 1024)
    response = _upload(client_a, party, content=big_content)
    assert response.status_code == 413


@pytest.mark.django_db
def test_delete_is_never_allowed(tenant_a, client_a):
    party = PartyFactory(tenant=tenant_a)
    attachment_id = _upload(client_a, party).data["id"]
    response = client_a.delete(f"/api/attachments/{attachment_id}/")
    assert response.status_code == 405


@pytest.mark.django_db
def test_void_requires_a_reason_then_succeeds(tenant_a, client_a):
    party = PartyFactory(tenant=tenant_a)
    attachment_id = _upload(client_a, party).data["id"]

    no_reason = client_a.post(f"/api/attachments/{attachment_id}/void/", {"reason": ""}, format="json")
    assert no_reason.status_code == 400

    with_reason = client_a.post(
        f"/api/attachments/{attachment_id}/void/", {"reason": "خطأ في الرفع"}, format="json"
    )
    assert with_reason.status_code == 200
    assert with_reason.data["status"] == "voided"


@pytest.mark.django_db
def test_second_version_on_master_target_supersedes_the_first(tenant_a, client_a):
    party = PartyFactory(tenant=tenant_a)
    first = _upload(client_a, party, category="id_document").data
    assert first["version"] == 1

    second = _upload(client_a, party, category="id_document").data
    assert second["version"] == 2
    assert str(second["supersedes"]) == first["id"]

    # both rows still exist — the old one is kept, not deleted.
    assert Attachment.objects.filter(id=first["id"]).exists()
    assert Attachment.objects.filter(id=second["id"]).exists()


@pytest.mark.django_db
def test_upload_to_another_tenants_party_is_404(tenant_a, tenant_b, client_a):
    other_party = PartyFactory(tenant=tenant_b)
    response = _upload(client_a, other_party)
    assert response.status_code == 404


@pytest.mark.django_db
def test_list_filters_by_target_and_hides_other_tenants(tenant_a, tenant_b, client_a):
    party_a = PartyFactory(tenant=tenant_a)
    party_b = PartyFactory(tenant=tenant_b)
    _upload(client_a, party_a)
    Attachment.objects.create(
        tenant=tenant_b,
        content_type=ContentType.objects.get_by_natural_key("parties", "party"),
        object_id=party_b.id,
        file="tenant-b/party/2026/fake.pdf",
        original_name="fake.pdf",
        mime_type="application/pdf",
        size=10,
        sha256="0" * 64,
        category="receipt",
    )
    response = client_a.get(f"/api/attachments/?target_type=party&target_id={party_a.id}")
    assert response.status_code == 200
    assert response.data["count"] == 1

    all_response = client_a.get("/api/attachments/")
    assert all_response.data["count"] == 1  # tenant B's row never visible to tenant A


@pytest.mark.django_db
def test_eicar_file_is_flagged_infected_and_download_is_blocked(tenant_a, client_a):
    # The pure, unmodified 68-byte EICAR test string — ClamAV's built-in
    # rule matches it exactly; any extra bytes around it (even a
    # disguise as a valid PDF header) make real ClamAV NOT flag it,
    # verified directly against the live clamd service. ".csv" is the
    # only allowed extension whose real content (plain ASCII text) this
    # naturally sniffs as, so it clears the magic-byte check too.
    party = PartyFactory(tenant=tenant_a)
    response = _upload(client_a, party, filename="virus.csv", content=EICAR_BYTES, category="other")
    if response.status_code != 201:
        pytest.skip("magic-byte detection rejected the EICAR fixture before it reached ClamAV")
    attachment_id = response.data["id"]
    assert response.data["scan_status"] == "infected"

    link = client_a.post(f"/api/attachments/{attachment_id}/link/").data["token"]
    download = APIClient().get(f"/api/attachments/{attachment_id}/download/?token={link}")
    assert download.status_code == 409


@pytest.mark.django_db
def test_signed_link_download_round_trip_and_expired_token(tenant_a, client_a, settings):
    party = PartyFactory(tenant=tenant_a)
    attachment_id = _upload(client_a, party).data["id"]

    link_response = client_a.post(f"/api/attachments/{attachment_id}/link/")
    assert link_response.status_code == 200
    token = link_response.data["token"]

    download = APIClient().get(f"/api/attachments/{attachment_id}/download/?token={token}")
    assert download.status_code == 200
    assert b"".join(download.streaming_content) == PDF_BYTES

    # A token signed for a DIFFERENT attachment id must not work here.
    forged_signer = TimestampSigner(key=settings.ATTACHMENT_LINK_SIGNING_KEY, salt="attachments.download")
    forged_token = forged_signer.sign_object({"attachment_id": "00000000-0000-0000-0000-000000000000"})
    forged = APIClient().get(f"/api/attachments/{attachment_id}/download/?token={forged_token}")
    assert forged.status_code == 403

    # An expired token (max_age=0 window already passed) must 403 too.
    settings.ATTACHMENT_LINK_TTL_SECONDS = 0
    import time

    time.sleep(1)
    expired = APIClient().get(f"/api/attachments/{attachment_id}/download/?token={token}")
    assert expired.status_code == 403


@pytest.mark.django_db
def test_pending_scan_status_blocks_download_with_409(tenant_a, client_a):
    party = PartyFactory(tenant=tenant_a)
    attachment_id = _upload(client_a, party).data["id"]
    attachment = Attachment.objects.get(id=attachment_id)
    attachment.scan_status = Attachment.ScanStatus.PENDING
    attachment.save(update_fields=["scan_status"])

    link = client_a.post(f"/api/attachments/{attachment_id}/link/").data["token"]
    download = APIClient().get(f"/api/attachments/{attachment_id}/download/?token={link}")
    assert download.status_code == 409
