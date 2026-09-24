"""Sprint 6.8: StructuredAddressMixin on Party (decision 20) and
log_master_data_change on TenantScopedViewSet (decision 21, F10) —
saving the collapsed structured-address section never touches the
free-text `address` field, and editing a master-data record's phone
writes an old/new AuditLog row readable via the tenant's own audit-log
endpoint (same one ChangeHistoryTab reads from).
"""

import pytest


@pytest.mark.django_db
def test_saving_structured_address_does_not_touch_free_text_address(tenant_a, client_a):
    created = client_a.post(
        "/api/parties/suppliers/",
        {"name": "Gulf Supplies Co", "address": {"raw": "شارع الملك فهد، الرياض"}},
        format="json",
    )
    assert created.status_code == 201, created.data

    updated = client_a.patch(
        f"/api/parties/suppliers/{created.data['id']}/",
        {"building_number": "1234", "street": "طريق الملك عبدالله", "district": "العليا",
         "city": "الرياض", "postal_code": "12345", "short_address": "RRAB1234"},
        format="json",
    )
    assert updated.status_code == 200, updated.data

    from apps.parties.models import Party

    party = Party.objects.get(id=created.data["id"])
    assert party.address == {"raw": "شارع الملك فهد، الرياض"}
    assert party.building_number == "1234"
    assert party.short_address == "RRAB1234"


@pytest.mark.django_db
def test_editing_supplier_phone_writes_change_history_with_old_and_new(tenant_a, client_a):
    created = client_a.post(
        "/api/parties/suppliers/", {"name": "Riyadh Trading", "phone": "0500000001"}, format="json"
    )
    assert created.status_code == 201, created.data
    party_id = created.data["id"]

    updated = client_a.patch(f"/api/parties/suppliers/{party_id}/", {"phone": "0500000002"}, format="json")
    assert updated.status_code == 200, updated.data

    log = client_a.get(f"/api/audit-log/?target_type=parties.party&target_id={party_id}")
    assert log.status_code == 200, log.data
    entries = [e for e in log.data["results"] if e["action"] == "parties.party.updated"]
    assert len(entries) == 1
    assert entries[0]["before"]["phone"] == "0500000001"
    assert entries[0]["after"]["phone"] == "0500000002"


@pytest.mark.django_db
def test_tenant_features_endpoint_requires_owner_to_patch(tenant_a, tenant_b, client_a, client_b):
    # client_b (via user_b, conftest.py) already seeded tenant_b's
    # system roles — fetch instead of re-seeding (unique_role_name_per_tenant).
    from rest_framework.test import APIClient

    from apps.access.models import Role

    from .factories import UserFactory

    roles_b = {r.name: r for r in Role.objects.filter(tenant=tenant_b, is_system=True)}
    accountant = UserFactory(tenant=tenant_b, email="accountant@tenant-features.test")
    accountant.roles.add(roles_b["Accountant"])
    accountant_client = APIClient()
    accountant_client.force_authenticate(user=accountant)

    denied = accountant_client.patch("/api/tenant-features/", {"cost_center_required": True}, format="json")
    assert denied.status_code == 403

    allowed = client_a.patch("/api/tenant-features/", {"cost_center_required": True}, format="json")
    assert allowed.status_code == 200, allowed.data
    assert allowed.data["cost_center_required"] is True


@pytest.mark.django_db
def test_tenant_features_tenant_isolation(tenant_a, tenant_b, client_a, client_b):
    a = client_a.patch("/api/tenant-features/", {"credit_limit_mode": "block"}, format="json")
    assert a.status_code == 200, a.data

    b = client_b.get("/api/tenant-features/")
    assert b.status_code == 200
    assert b.data["credit_limit_mode"] == "warn"
