"""Sprint 5.5 (block 5.5.0, CFO_REVIEW_1 C10): Party.iban / Bank.iban,
validate_iban (mod-97 + country length), IbanChangeRequest on the
shared approval engine (fixed rule, required_role=Owner), and the
payment-voucher guard — all against the real HTTP API and real
Postgres, matching this project's testing philosophy throughout.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.access.models import Role, UserEntityAccess
from apps.approvals.models import ApprovalRule
from apps.organization.models import LegalEntity
from apps.parties.models import Party
from apps.platform.models import AuditLog

from .factories import PartyFactory, UserFactory

# Valid-checksum test IBANs (verified mod-97 == 1 offline; SA/EG match
# their required lengths, DE is the standard textbook example used here
# purely as "a valid IBAN for a country with no special-cased length").
SA_IBAN = "SA0380000000608010167519"
EG_IBAN = "EG720019000500000000026318000"
DE_IBAN = "DE89370400440532013000"


def _branch(tenant):
    return LegalEntity.objects.get(tenant=tenant, entity_type=LegalEntity.Type.BRANCH)


def _seed_iban_rule(tenant):
    """Registration (apps.accounts.serializers.RegisterSerializer) and
    approvals/migrations/0005 both seed this fixed rule for real
    tenants — pytest's tenant_a/tenant_b fixtures build a tenant
    directly via TenantFactory, bypassing both, so every workflow test
    below seeds it explicitly (same pattern already used throughout
    tests/test_approvals.py and tests/test_journal_engine.py)."""
    owner_role = Role.objects.get(tenant=tenant, name="Owner", is_system=True)
    return ApprovalRule.objects.get_or_create(
        tenant=tenant, doc_type=ApprovalRule.DocType.IBAN_CHANGE, min_amount=0,
        defaults={"required_role": owner_role, "is_active": True},
    )[0]


def _make_bank(client, tenant, iban=""):
    payload = {"legal_entity": str(_branch(tenant).id), "name": "Bank", "currency": "SAR"}
    if iban:
        payload["iban"] = iban
    response = client.post("/api/banks/", payload, format="json")
    assert response.status_code == 201, response.data
    return response.data


def _make_supplier(client, iban="", country_code="SA"):
    payload = {"name": "Supplier", "party_type": "organization", "country_code": country_code}
    if iban:
        payload["iban"] = iban
    response = client.post("/api/parties/suppliers/", payload, format="json")
    assert response.status_code == 201, response.data
    return response.data


def _accountant(tenant):
    """A second, non-Owner active user in the same tenant — only needed
    to exercise segregation-of-duties checks (a single-active-user
    tenant is exempted from them, see
    test_single_active_user_tenant_owner_approves_own_request)."""
    role = Role.objects.get(tenant=tenant, name="Accountant", is_system=True)
    user = UserFactory(tenant=tenant, email=f"accountant-{tenant.id}@iban.test")
    user.roles.add(role)
    UserEntityAccess.objects.create(user=user, legal_entity=_branch(tenant))
    client = APIClient()
    client.force_authenticate(user=user)
    return user, client


def _attach_iban_letter(client, request_id):
    upload = SimpleUploadedFile(
        "iban-letter.pdf",
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF",
        content_type="application/octet-stream",
    )
    response = client.post(
        "/api/attachments/",
        {"target_type": "iban_change_request", "target_id": request_id, "category": "bank_letter", "file": upload},
        format="multipart",
    )
    assert response.status_code == 201, response.data
    return response.data


def _submit_request(client, request_id):
    _attach_iban_letter(client, request_id)
    response = client.post(f"/api/iban-requests/{request_id}/submit/")
    assert response.status_code == 200, response.data
    assert response.data["status"] == "pending_approval"
    return response.data


# ---------------------------------------------------------------------
# validate_iban format/checksum
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_bank_with_valid_saudi_iban_is_accepted(tenant_a, client_a):
    bank = _make_bank(client_a, tenant_a, iban=SA_IBAN)
    assert bank["iban"] == SA_IBAN


@pytest.mark.django_db
def test_saudi_iban_wrong_length_rejected(tenant_a, client_a):
    response = client_a.post(
        "/api/banks/",
        {"legal_entity": str(_branch(tenant_a).id), "name": "Bank", "currency": "SAR", "iban": SA_IBAN[:23]},
        format="json",
    )
    assert response.status_code == 400, response.data


@pytest.mark.django_db
def test_iban_failing_mod97_checksum_rejected(tenant_a, client_a):
    bad = SA_IBAN[:-1] + ("0" if SA_IBAN[-1] != "0" else "1")
    response = client_a.post(
        "/api/banks/",
        {"legal_entity": str(_branch(tenant_a).id), "name": "Bank", "currency": "SAR", "iban": bad},
        format="json",
    )
    assert response.status_code == 400, response.data


@pytest.mark.django_db
def test_valid_egyptian_iban_accepted(tenant_a, client_a):
    supplier = _make_supplier(client_a, iban=EG_IBAN, country_code="EG")
    assert supplier["iban"] == EG_IBAN


@pytest.mark.django_db
def test_valid_general_iban_for_another_country_accepted_on_bank(tenant_a, client_a):
    # Bank has no country_code cross-check (unlike Party) — any
    # correctly-shaped, checksum-valid IBAN is accepted regardless of
    # the tenant's own default country.
    bank = _make_bank(client_a, tenant_a, iban=DE_IBAN)
    assert bank["iban"] == DE_IBAN


# ---------------------------------------------------------------------
# first-entry-free, edit-of-existing-value-rejected (decision 6)
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_patch_over_existing_iban_rejected(tenant_a, client_a):
    """Reproduces the exact placeholder IBAN found in real dev data
    before this sprint (PartyRole.details['iban'] on a supplier,
    migrated verbatim into Party.iban by 0003_backfill_party_iban_
    from_role_details.py, unvalidated) — confirms editing a non-empty
    value is rejected regardless of whether that value itself is
    actually well-formed, while re-submitting the identical value is a
    no-op and still allowed."""
    placeholder = "SA0000000000000000000000"  # real value found in dev data — deliberately invalid checksum
    supplier = PartyFactory(tenant=tenant_a, country_code="SA")
    supplier.iban = placeholder
    supplier.save(update_fields=["iban"])
    from apps.parties.models import PartyRole

    PartyRole.objects.create(party=supplier, role=PartyRole.Role.SUPPLIER)

    response = client_a.patch(
        f"/api/parties/suppliers/{supplier.id}/", {"iban": SA_IBAN}, format="json"
    )
    assert response.status_code == 400, response.data
    supplier.refresh_from_db()
    assert supplier.iban == placeholder

    same = client_a.patch(
        f"/api/parties/suppliers/{supplier.id}/", {"iban": placeholder}, format="json"
    )
    assert same.status_code == 200, same.data


@pytest.mark.django_db
def test_first_iban_entry_on_empty_field_is_free(tenant_a, client_a):
    bank = _make_bank(client_a, tenant_a)
    assert bank["iban"] == ""
    response = client_a.patch(f"/api/banks/{bank['id']}/", {"iban": SA_IBAN}, format="json")
    assert response.status_code == 200, response.data
    assert response.data["iban"] == SA_IBAN


# ---------------------------------------------------------------------
# IbanChangeRequest workflow
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_submit_without_attachment_rejected(tenant_a, client_a):
    _seed_iban_rule(tenant_a)
    bank = _make_bank(client_a, tenant_a, iban=SA_IBAN)
    create = client_a.post(
        "/api/iban-requests/",
        {"target_type": "bank", "target_id": bank["id"], "new_iban": DE_IBAN, "reason": "تحديث"},
        format="json",
    )
    assert create.status_code == 201, create.data
    submit = client_a.post(f"/api/iban-requests/{create.data['id']}/submit/")
    assert submit.status_code == 400, submit.data


@pytest.mark.django_db
def test_full_approval_flow_changes_iban_and_logs_audit(tenant_a, client_a):
    _seed_iban_rule(tenant_a)
    bank = _make_bank(client_a, tenant_a, iban=SA_IBAN)
    accountant_user, accountant_client = _accountant(tenant_a)

    create = accountant_client.post(
        "/api/iban-requests/",
        {"target_type": "bank", "target_id": bank["id"], "new_iban": DE_IBAN, "reason": "تغيير بنك"},
        format="json",
    )
    assert create.status_code == 201, create.data
    request_id = create.data["id"]
    _submit_request(accountant_client, request_id)
    # No auto-approval regardless of the doc's amount (always 0) — the
    # fixed rule always matches, so it's genuinely PENDING_APPROVAL.
    bank_check = accountant_client.get(f"/api/banks/{bank['id']}/")
    assert bank_check.data["iban"] == SA_IBAN

    # Creator cannot approve their own request (segregation of duties).
    self_approve = accountant_client.post(f"/api/iban-requests/{request_id}/approve/")
    assert self_approve.status_code == 403, self_approve.data

    approve = client_a.post(f"/api/iban-requests/{request_id}/approve/")
    assert approve.status_code == 200, approve.data
    assert approve.data["status"] == "approved"

    bank_after = client_a.get(f"/api/banks/{bank['id']}/")
    assert bank_after.data["iban"] == DE_IBAN

    log = AuditLog.objects.filter(action="iban_change_request.applied", target_id=bank["id"]).first()
    assert log is not None
    assert log.before == {"iban": SA_IBAN}
    assert log.after == {"iban": DE_IBAN}


@pytest.mark.django_db
def test_rejected_request_leaves_iban_unchanged(tenant_a, client_a):
    _seed_iban_rule(tenant_a)
    bank = _make_bank(client_a, tenant_a, iban=SA_IBAN)
    accountant_user, accountant_client = _accountant(tenant_a)
    create = accountant_client.post(
        "/api/iban-requests/",
        {"target_type": "bank", "target_id": bank["id"], "new_iban": DE_IBAN, "reason": "تغيير"},
        format="json",
    )
    request_id = create.data["id"]
    _submit_request(accountant_client, request_id)

    reject = client_a.post(f"/api/iban-requests/{request_id}/reject/", {"reason": "لا يوجد خطاب رسمي"}, format="json")
    assert reject.status_code == 200, reject.data
    assert reject.data["status"] == "draft"

    bank_after = client_a.get(f"/api/banks/{bank['id']}/")
    assert bank_after.data["iban"] == SA_IBAN


@pytest.mark.django_db
def test_second_pending_request_for_same_target_rejected(tenant_a, client_a):
    _seed_iban_rule(tenant_a)
    bank = _make_bank(client_a, tenant_a, iban=SA_IBAN)
    first = client_a.post(
        "/api/iban-requests/",
        {"target_type": "bank", "target_id": bank["id"], "new_iban": DE_IBAN, "reason": "أول طلب"},
        format="json",
    )
    assert first.status_code == 201, first.data
    second = client_a.post(
        "/api/iban-requests/",
        {"target_type": "bank", "target_id": bank["id"], "new_iban": EG_IBAN, "reason": "طلب ثانٍ"},
        format="json",
    )
    assert second.status_code == 400, second.data


@pytest.mark.django_db
def test_single_active_user_tenant_owner_approves_own_request(tenant_a, client_a):
    # tenant_a's only active user is the Owner (user_a) — the 3.15.1
    # single-active-user exemption lets them create AND approve.
    _seed_iban_rule(tenant_a)
    bank = _make_bank(client_a, tenant_a, iban=SA_IBAN)
    create = client_a.post(
        "/api/iban-requests/",
        {"target_type": "bank", "target_id": bank["id"], "new_iban": DE_IBAN, "reason": "تحديث"},
        format="json",
    )
    request_id = create.data["id"]
    _submit_request(client_a, request_id)

    approve = client_a.post(f"/api/iban-requests/{request_id}/approve/")
    assert approve.status_code == 200, approve.data
    bank_after = client_a.get(f"/api/banks/{bank['id']}/")
    assert bank_after.data["iban"] == DE_IBAN


# ---------------------------------------------------------------------
# approval-rule screen: the fixed rule cannot be edited/deleted
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_fixed_iban_change_rule_cannot_be_deleted_or_edited(tenant_a, client_a):
    rule = _seed_iban_rule(tenant_a)
    destroy = client_a.delete(f"/api/approval-rules/{rule.id}/")
    assert destroy.status_code == 409, destroy.data
    update = client_a.patch(f"/api/approval-rules/{rule.id}/", {"min_amount": "100"}, format="json")
    assert update.status_code == 409, update.data


# ---------------------------------------------------------------------
# payment-voucher guard
# ---------------------------------------------------------------------


def _payment_payload(tenant, treasury, supplier):
    # A bank (not a cash box) on purpose — an overdrawn bank balance is
    # only a warning (5.3 decision 4), while a cash box hard-blocks at
    # 400, which would be indistinguishable from this test's own IBAN
    # assertions. Keeps this test isolated to the one thing it checks.
    return {
        "voucher_type": "payment",
        "legal_entity": str(_branch(tenant).id),
        "date": "2026-01-05",
        "treasury_kind": "bank",
        "treasury_id": treasury["id"],
        "party": str(supplier.id),
        "party_role": "supplier",
        "lines": [{"line_type": "on_account", "amount_fc": "100.00"}],
    }


@pytest.mark.django_db
def test_payment_voucher_blocked_while_iban_request_pending(tenant_a, client_a):
    _seed_iban_rule(tenant_a)
    supplier_data = _make_supplier(client_a, iban=SA_IBAN)
    supplier = Party.objects.get(id=supplier_data["id"])
    treasury_bank = _make_bank(client_a, tenant_a)

    create = client_a.post(
        "/api/iban-requests/",
        {"target_type": "party", "target_id": str(supplier.id), "new_iban": DE_IBAN, "reason": "تحديث"},
        format="json",
    )
    assert create.status_code == 201, create.data
    _submit_request(client_a, create.data["id"])

    payment = client_a.post("/api/vouchers/", _payment_payload(tenant_a, treasury_bank, supplier), format="json")
    assert payment.status_code == 409, payment.data


@pytest.mark.django_db
def test_payment_voucher_after_recent_approved_iban_change_gets_warning(tenant_a, client_a):
    _seed_iban_rule(tenant_a)
    supplier_data = _make_supplier(client_a, iban=SA_IBAN)
    supplier = Party.objects.get(id=supplier_data["id"])
    treasury_bank = _make_bank(client_a, tenant_a)
    accountant_user, accountant_client = _accountant(tenant_a)

    create = accountant_client.post(
        "/api/iban-requests/",
        {"target_type": "party", "target_id": str(supplier.id), "new_iban": DE_IBAN, "reason": "تحديث"},
        format="json",
    )
    request_id = create.data["id"]
    _submit_request(accountant_client, request_id)
    approve = client_a.post(f"/api/iban-requests/{request_id}/approve/")
    assert approve.status_code == 200, approve.data

    payment = client_a.post("/api/vouchers/", _payment_payload(tenant_a, treasury_bank, supplier), format="json")
    assert payment.status_code == 201, payment.data
    post = client_a.post(f"/api/vouchers/{payment.data['id']}/post/")
    assert post.status_code == 200, post.data
    assert any("IBAN" in w for w in post.data["warnings"])


# ---------------------------------------------------------------------
# tenant isolation
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_iban_requests_are_tenant_isolated(tenant_a, client_a, tenant_b, client_b):
    _seed_iban_rule(tenant_a)
    bank_a = _make_bank(client_a, tenant_a, iban=SA_IBAN)
    create = client_a.post(
        "/api/iban-requests/",
        {"target_type": "bank", "target_id": bank_a["id"], "new_iban": DE_IBAN, "reason": "تحديث"},
        format="json",
    )
    request_id = create.data["id"]

    cross_get = client_b.get(f"/api/iban-requests/{request_id}/")
    assert cross_get.status_code == 404

    cross_create = client_b.post(
        "/api/iban-requests/",
        {"target_type": "bank", "target_id": bank_a["id"], "new_iban": DE_IBAN, "reason": "تحديث"},
        format="json",
    )
    assert cross_create.status_code == 400, cross_create.data

    listing = client_b.get("/api/iban-requests/")
    assert all(row["id"] != request_id for row in listing.data.get("results", listing.data))


@pytest.mark.django_db
def test_delete_draft_iban_request_soft_deletes(tenant_a, client_a):
    _seed_iban_rule(tenant_a)
    bank = _make_bank(client_a, tenant_a, iban=SA_IBAN)
    create = client_a.post(
        "/api/iban-requests/",
        {"target_type": "bank", "target_id": bank["id"], "new_iban": DE_IBAN, "reason": "تحديث"},
        format="json",
    )
    assert create.status_code == 201, create.data
    request_id = create.data["id"]

    deleted = client_a.delete(f"/api/iban-requests/{request_id}/")
    assert deleted.status_code == 204, deleted.data

    from apps.treasury.models import IbanChangeRequest

    stored = IbanChangeRequest.objects.get(id=request_id)
    assert stored.deleted_at is not None
    assert client_a.get(f"/api/iban-requests/{request_id}/").status_code == 404


@pytest.mark.django_db
def test_delete_pending_iban_request_returns_409(tenant_a, client_a):
    _seed_iban_rule(tenant_a)
    bank = _make_bank(client_a, tenant_a, iban=SA_IBAN)
    accountant_user, accountant_client = _accountant(tenant_a)
    create = accountant_client.post(
        "/api/iban-requests/",
        {"target_type": "bank", "target_id": bank["id"], "new_iban": DE_IBAN, "reason": "تحديث"},
        format="json",
    )
    request_id = create.data["id"]
    _submit_request(accountant_client, request_id)

    deleted = accountant_client.delete(f"/api/iban-requests/{request_id}/")
    assert deleted.status_code == 409, deleted.data


@pytest.mark.django_db
def test_delete_approved_iban_request_returns_409(tenant_a, client_a):
    _seed_iban_rule(tenant_a)
    bank = _make_bank(client_a, tenant_a, iban=SA_IBAN)
    accountant_user, accountant_client = _accountant(tenant_a)
    create = accountant_client.post(
        "/api/iban-requests/",
        {"target_type": "bank", "target_id": bank["id"], "new_iban": DE_IBAN, "reason": "تحديث"},
        format="json",
    )
    request_id = create.data["id"]
    _submit_request(accountant_client, request_id)
    approve = client_a.post(f"/api/iban-requests/{request_id}/approve/")
    assert approve.status_code == 200, approve.data

    deleted = client_a.delete(f"/api/iban-requests/{request_id}/")
    assert deleted.status_code == 409, deleted.data


@pytest.mark.django_db
def test_deleting_a_draft_request_frees_the_target_for_a_fresh_one(tenant_a, client_a):
    """Sprint 6.6.5 (§6.2, self-caught fix): before this fix, deleting
    a still-DRAFT request left it matching create_iban_change_request's
    own "already pending" guard (status__in=[DRAFT, PENDING_APPROVAL]
    had no deleted_at filter) — a soft-deleted draft would keep
    blocking a fresh request on the same target forever."""
    _seed_iban_rule(tenant_a)
    bank = _make_bank(client_a, tenant_a, iban=SA_IBAN)
    create = client_a.post(
        "/api/iban-requests/",
        {"target_type": "bank", "target_id": bank["id"], "new_iban": DE_IBAN, "reason": "تحديث"},
        format="json",
    )
    request_id = create.data["id"]
    assert client_a.delete(f"/api/iban-requests/{request_id}/").status_code == 204

    second = client_a.post(
        "/api/iban-requests/",
        {"target_type": "bank", "target_id": bank["id"], "new_iban": DE_IBAN, "reason": "تحديث ثانٍ"},
        format="json",
    )
    assert second.status_code == 201, second.data
