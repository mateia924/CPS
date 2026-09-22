"""Sprint 4.1 (docs/SYSTEM_ANALYSIS.md 3.4; ARCH_REVIEW_1.md §3.4):
apps.numbering — the atomic replacement for the COUNT-based
generate_invoice_number/generate_party_code (ARCH_REVIEW_1.md debts
#1/#2, both flagged "عالية" — high severity)."""

import threading
from datetime import date
from decimal import Decimal

import pytest
from django.db import connection
from rest_framework.test import APIClient

from apps.access.services import seed_default_roles
from apps.numbering.models import DocumentNumberingSetting, DocumentSequence
from apps.numbering.services import DEFAULT_PREFIXES, next_document_number
from apps.organization.services import create_default_legal_entities
from apps.parties.models import PartyRole
from apps.parties.services import generate_party_code
from apps.sales.services import create_invoice

from .factories import LegalEntityFactory, PartyFactory, ProductFactory, TenantFactory, UserFactory


@pytest.mark.django_db
def test_next_document_number_is_sequential_and_gap_free(db):
    tenant = TenantFactory()
    entity = LegalEntityFactory(tenant=tenant)
    numbers = [
        next_document_number(tenant, "invoice", legal_entity=entity, date=date(2026, 1, 1))
        for _ in range(3)
    ]
    assert numbers == ["INV-2026-00001", "INV-2026-00002", "INV-2026-00003"]


@pytest.mark.django_db
def test_sequence_scope_is_per_legal_entity(db):
    tenant = TenantFactory()
    entity_a = LegalEntityFactory(tenant=tenant)
    entity_b = LegalEntityFactory(tenant=tenant)
    first_a = next_document_number(tenant, "invoice", legal_entity=entity_a, date=date(2026, 1, 1))
    first_b = next_document_number(tenant, "invoice", legal_entity=entity_b, date=date(2026, 1, 1))
    assert first_a == "INV-2026-00001"
    assert first_b == "INV-2026-00001"  # independent scope, not a shared counter


@pytest.mark.django_db
def test_sequence_resets_yearly_by_default(db):
    tenant = TenantFactory()
    entity = LegalEntityFactory(tenant=tenant)
    next_document_number(tenant, "invoice", legal_entity=entity, date=date(2026, 12, 31))
    second_year_first = next_document_number(tenant, "invoice", legal_entity=entity, date=date(2027, 1, 1))
    assert second_year_first == "INV-2027-00001"


@pytest.mark.django_db
def test_sequence_does_not_reset_when_reset_yearly_is_false(db):
    tenant = TenantFactory()
    entity = LegalEntityFactory(tenant=tenant)
    DocumentNumberingSetting.objects.create(
        tenant=tenant, doc_type="invoice", prefix="INV", reset_yearly=False
    )
    next_document_number(tenant, "invoice", legal_entity=entity, date=date(2026, 12, 31))
    second_year_first = next_document_number(tenant, "invoice", legal_entity=entity, date=date(2027, 1, 1))
    # Display year still reflects the real date; the running count keeps
    # climbing instead of resetting.
    assert second_year_first == "INV-2027-00002"


@pytest.mark.django_db
def test_custom_prefix_is_honored(db):
    tenant = TenantFactory()
    entity = LegalEntityFactory(tenant=tenant)
    DocumentNumberingSetting.objects.create(tenant=tenant, doc_type="invoice", prefix="FT")
    number = next_document_number(tenant, "invoice", legal_entity=entity, date=date(2026, 1, 1))
    assert number == "FT-2026-00001"


@pytest.mark.django_db
def test_party_codes_are_prefixed_per_role_and_scoped_per_tenant_only(db):
    tenant = TenantFactory()
    customer_code = generate_party_code(tenant, PartyRole.Role.CUSTOMER)
    supplier_code = generate_party_code(tenant, PartyRole.Role.SUPPLIER)
    employee_code = generate_party_code(tenant, PartyRole.Role.EMPLOYEE)
    affiliate_code = generate_party_code(tenant, PartyRole.Role.AFFILIATE)
    second_customer_code = generate_party_code(tenant, PartyRole.Role.CUSTOMER)

    assert customer_code.startswith("CUS-")
    assert supplier_code.startswith("SUP-")
    assert employee_code.startswith("EMP-")
    assert affiliate_code.startswith("AFF-")
    assert second_customer_code.endswith("-00002")  # independent of the other roles' counters


@pytest.mark.django_db
def test_party_sequence_has_no_legal_entity_dimension(db):
    tenant = TenantFactory()
    generate_party_code(tenant, PartyRole.Role.CUSTOMER)
    sequence = DocumentSequence.objects.get(tenant=tenant, doc_type="party_customer")
    assert sequence.legal_entity_id is None


@pytest.mark.django_db(transaction=True)
def test_50_concurrent_invoice_creations_get_50_unique_gapless_numbers():
    tenant = TenantFactory()
    company, entity = create_default_legal_entities(tenant, tenant.name)
    party = PartyFactory(tenant=tenant)
    product = ProductFactory(tenant=tenant)
    line_inputs = [{"product": product, "quantity": Decimal("1"), "cost_center": None}]

    results = [None] * 50
    errors = []

    def worker(index):
        try:
            invoice = create_invoice(tenant, party, entity, date(2026, 6, 1), line_inputs)
            results[index] = invoice.number
        except Exception as exc:  # noqa: BLE001 — surfaced via `errors` for the assertion below
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(set(results)) == 50
    expected = {f"INV-2026-{n:05d}" for n in range(1, 51)}
    assert set(results) == expected


# ---------------------------------------------------------------------
# Settings screen: /api/document-numbering-settings/
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_numbering_settings_list_covers_every_known_doc_type(db):
    tenant = TenantFactory()
    roles = seed_default_roles(tenant)
    owner = UserFactory(tenant=tenant, email="owner@numbering-list.test")
    owner.roles.add(roles["Owner"])
    client = APIClient()
    client.force_authenticate(user=owner)

    response = client.get("/api/document-numbering-settings/")

    assert response.status_code == 200
    doc_types = {row["doc_type"] for row in response.data["results"]}
    assert doc_types == set(DEFAULT_PREFIXES)


@pytest.mark.django_db
def test_owner_can_edit_prefix_and_reset_yearly(db):
    tenant = TenantFactory()
    roles = seed_default_roles(tenant)
    owner = UserFactory(tenant=tenant, email="owner@numbering-edit.test")
    owner.roles.add(roles["Owner"])
    client = APIClient()
    client.force_authenticate(user=owner)
    client.get("/api/document-numbering-settings/")  # lazily creates the rows
    setting = DocumentNumberingSetting.objects.get(tenant=tenant, doc_type="invoice")

    response = client.patch(
        f"/api/document-numbering-settings/{setting.id}/",
        {"prefix": "FAT", "reset_yearly": False},
        format="json",
    )

    assert response.status_code == 200
    setting.refresh_from_db()
    assert setting.prefix == "FAT"
    assert setting.reset_yearly is False


@pytest.mark.django_db
def test_viewer_without_manage_permission_cannot_edit(db):
    tenant = TenantFactory()
    roles = seed_default_roles(tenant)
    viewer = UserFactory(tenant=tenant, email="viewer@numbering-edit.test")
    viewer.roles.add(roles["Viewer"])
    client = APIClient()
    client.force_authenticate(user=viewer)
    setting = DocumentNumberingSetting.objects.create(tenant=tenant, doc_type="invoice", prefix="INV")

    response = client.patch(
        f"/api/document-numbering-settings/{setting.id}/", {"prefix": "X"}, format="json"
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_numbering_settings_are_tenant_isolated(db):
    tenant_a = TenantFactory()
    tenant_b = TenantFactory()
    roles_a = seed_default_roles(tenant_a)
    owner_a = UserFactory(tenant=tenant_a, email="owner@numbering-iso-a.test")
    owner_a.roles.add(roles_a["Owner"])
    setting_b = DocumentNumberingSetting.objects.create(tenant=tenant_b, doc_type="invoice", prefix="INV")

    client = APIClient()
    client.force_authenticate(user=owner_a)
    response = client.get(f"/api/document-numbering-settings/{setting_b.id}/")

    assert response.status_code == 404
