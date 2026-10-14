"""Sprint 7.4: stock document API (SR/SI/ST) on top of the 7.3 engine.

Every guard here is asserted at the API — a posted document is refused by
the endpoint, not merely shown without a button.
"""

from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APIClient

from apps.access.models import Role, UserEntityAccess
from apps.attachments.models import Attachment
from apps.inventory.models import StockDocument, StockDocumentLine, StockLevel, StockMove, Warehouse
from apps.organization.models import LegalEntity
from apps.sales.models import Product

from .factories import ProductFactory, UserFactory

D = Decimal
URL = "/api/stock-documents/"


class _Setup:
    def __init__(self, tenant):
        tenant.features.inventory = True
        tenant.features.save(update_fields=["inventory"])
        self.tenant = tenant
        self.company = LegalEntity.objects.get(tenant=tenant, code="MAIN")
        self.branch1 = LegalEntity.objects.get(tenant=tenant, code="MAIN-01")
        self.branch2 = LegalEntity.objects.create(
            tenant=tenant, code="MAIN-02", name="فرع جدة", entity_type=LegalEntity.Type.BRANCH, parent=self.company,
        )
        self.w1 = Warehouse.objects.create(tenant=tenant, legal_entity=self.branch1, code="W1", name="مستودع الرياض")
        self.w2 = Warehouse.objects.create(tenant=tenant, legal_entity=self.branch2, code="W2", name="مستودع جدة")
        self.item = ProductFactory(tenant=tenant, name="صنف اختبار", item_type=Product.ItemType.STOCK)

    def payload(self, kind="receipt", qty="10", unit_cost="100", warehouse=None, to_warehouse=None, **extra):
        warehouse = warehouse or self.w1
        line = {"item": str(self.item.id), "qty": qty}
        if kind == "receipt":
            line["unit_cost"] = unit_cost
        line.update(extra.pop("line", {}))
        body = {
            "kind": kind, "legal_entity": str(warehouse.legal_entity_id), "warehouse": str(warehouse.id),
            "date": "2026-06-10", "lines": [line],
        }
        if to_warehouse is not None:
            body["to_warehouse"] = str(to_warehouse.id)
        body.update(extra)
        return body

    def user_client(self, entity, role="Warehouse Keeper", email="keeper@tenant-a.test"):
        user = UserFactory(tenant=self.tenant, email=email)
        user.roles.add(Role.objects.get(tenant=self.tenant, name=role))
        UserEntityAccess.objects.create(user=user, legal_entity=entity)
        client = APIClient()
        client.force_authenticate(user=user)
        return client


def _posted(client, setup, **kw):
    """Create -> submit -> post through the API, asserting each step."""
    created = client.post(URL, setup.payload(**kw), format="json")
    assert created.status_code == 201, created.content
    doc_id = created.data["id"]
    submitted = client.post(f"{URL}{doc_id}/submit/")
    assert submitted.status_code == 200, submitted.content  # no ApprovalRule on tenant_a -> auto-approved
    posted = client.post(f"{URL}{doc_id}/post/")
    assert posted.status_code == 200, posted.content
    return posted.data


@pytest.fixture
def setup(tenant_a, user_a):
    return _Setup(tenant_a)


# ------------------------------------------------------------ happy path


@pytest.mark.django_db
def test_receipt_create_submit_post_through_the_api(setup, client_a):
    data = _posted(client_a, setup)
    assert data["status"] == "posted"
    assert data["number"].startswith("SR-")
    assert data["total_value"] == "1000.00" and data["total_is_estimate"] is False
    assert len(data["journal_entries"]) == 1
    assert StockLevel.objects.get(item=setup.item, warehouse=setup.w1).qty_on_hand == D("10")


@pytest.mark.django_db
def test_totals_are_computed_server_side_and_a_client_total_is_ignored(setup, client_a):
    created = client_a.post(URL, setup.payload(total_value="1.00", total_qty="999"), format="json")
    assert created.status_code == 201
    assert created.data["total_value"] == "1000.00"
    assert D(created.data["total_qty"]) == D("10")


@pytest.mark.django_db
def test_an_issue_before_posting_shows_an_estimate_at_the_current_average(setup, client_a):
    _posted(client_a, setup)
    created = client_a.post(URL, setup.payload(kind="issue", qty="4"), format="json")
    assert created.data["total_value"] == "400.00" and created.data["total_is_estimate"] is True


# ------------------------------------------------- engine errors via API


@pytest.mark.django_db
def test_an_engine_error_reaches_the_client_as_400_with_its_arabic_message(setup, client_a):
    _posted(client_a, setup, qty="8")
    created = client_a.post(URL, setup.payload(kind="issue", qty="9"), format="json")
    client_a.post(f"{URL}{created.data['id']}/submit/")

    response = client_a.post(f"{URL}{created.data['id']}/post/")

    assert response.status_code == 400
    assert "صنف اختبار" in response.data["detail"] and "مستودع الرياض" in response.data["detail"]
    assert "8" in response.data["detail"]


@pytest.mark.django_db
def test_reversing_a_stock_journal_entry_directly_is_still_409(setup, client_a):
    data = _posted(client_a, setup)
    entry_id = data["journal_entries"][0]["id"]
    response = client_a.post(f"/api/journal-entries/{entry_id}/reverse/", {"reason": "test"}, format="json")
    assert response.status_code == 409


@pytest.mark.django_db
def test_reverse_through_the_api_creates_the_opposite_document(setup, client_a):
    data = _posted(client_a, setup)
    response = client_a.post(f"{URL}{data['id']}/reverse/", {"reason": "إدخال خاطئ", "date": "2026-06-10"}, format="json")
    assert response.status_code == 201, response.content
    assert str(response.data["reverses"]) == str(data["id"]) and response.data["status"] == "posted"
    assert StockLevel.objects.get(item=setup.item, warehouse=setup.w1).qty_on_hand == D("0")


@pytest.mark.django_db
def test_a_duplicate_serial_in_one_document_is_a_clear_400(setup, client_a):
    setup.item.tracking = "serial"
    setup.item.save(update_fields=["tracking"])
    body = setup.payload(qty="2", line={"serials": ["SN-1", "SN-1"]})
    response = client_a.post(URL, body, format="json")
    assert response.status_code == 400
    assert "SN-1" in response.data["detail"] and "مكرر" in response.data["detail"]


# --------------------------------------------- posted-immutability at API


@pytest.mark.django_db
def test_the_api_refuses_to_delete_a_posted_document(setup, client_a):
    data = _posted(client_a, setup)
    response = client_a.delete(f"{URL}{data['id']}/")
    assert response.status_code == 409
    assert StockDocument.objects.filter(pk=data["id"], deleted_at__isnull=True).exists()


@pytest.mark.django_db
def test_the_api_refuses_to_edit_a_posted_document(setup, client_a):
    data = _posted(client_a, setup)
    response = client_a.patch(f"{URL}{data['id']}/", {"reference": "تعديل", "notes": "x"}, format="json")
    assert response.status_code == 409, response.content
    assert StockDocument.objects.get(pk=data["id"]).reference == ""


@pytest.mark.django_db
def test_a_draft_is_editable_and_its_lines_are_replaced(setup, client_a):
    created = client_a.post(URL, setup.payload(), format="json")
    response = client_a.patch(
        f"{URL}{created.data['id']}/", {"reference": "PO-7", "lines": [{"item": str(setup.item.id), "qty": "3", "unit_cost": "50"}]},
        format="json",
    )
    assert response.status_code == 200, response.content
    assert response.data["reference"] == "PO-7" and response.data["total_value"] == "150.00"
    assert StockDocumentLine.objects.filter(document_id=created.data["id"]).count() == 1


@pytest.mark.django_db
def test_deleting_a_draft_soft_deletes_it_with_its_lines_and_attachments(setup, client_a):
    created = client_a.post(URL, setup.payload(), format="json")
    doc_id = created.data["id"]
    attachment = Attachment.objects.create(
        tenant=setup.tenant, content_type=ContentType.objects.get_for_model(StockDocument), object_id=doc_id,
        file="tenant-a/stock/2026/delivery-note.pdf", original_name="delivery-note.pdf",
        mime_type="application/pdf", size=10, sha256="0" * 64, category="receipt",
    )

    response = client_a.delete(f"{URL}{doc_id}/")

    assert response.status_code == 204
    document = StockDocument.objects.get(pk=doc_id)
    assert document.deleted_at is not None  # soft, never a SQL DELETE
    assert client_a.get(f"{URL}{doc_id}/").status_code == 404
    assert str(doc_id) not in [str(row["id"]) for row in client_a.get(URL).data["results"]]
    assert StockDocumentLine.objects.filter(document_id=doc_id).count() == 1  # kept, unreachable with it
    attachment.refresh_from_db()
    assert attachment.status == Attachment.Status.VOIDED


# ------------------------------------------------------- entity scoping


@pytest.mark.django_db
def test_a_document_of_another_entity_is_404_not_403(setup, client_a):
    other_company = LegalEntity.objects.create(
        tenant=setup.tenant, code="OTHER", name="شركة أخرى", entity_type=LegalEntity.Type.COMPANY,
    )
    other_wh = Warehouse.objects.create(tenant=setup.tenant, legal_entity=other_company, code="WO", name="مستودع آخر")
    created = client_a.post(URL, setup.payload(warehouse=other_wh), format="json")
    keeper = setup.user_client(setup.branch1)

    assert keeper.get(f"{URL}{created.data['id']}/").status_code == 404
    assert keeper.post(f"{URL}{created.data['id']}/post/").status_code == 404
    assert keeper.delete(f"{URL}{created.data['id']}/").status_code == 404


@pytest.mark.django_db
def test_confirming_a_transfer_from_a_non_destination_entity_is_403(setup, client_a):
    _posted(client_a, setup)
    transfer = _posted(client_a, setup, kind="transfer", qty="4", to_warehouse=setup.w2)
    source_keeper = setup.user_client(setup.branch1, email="source@tenant-a.test")

    response = source_keeper.post(f"{URL}{transfer['id']}/confirm-receipt/", {"date": "2026-06-11"}, format="json")

    assert response.status_code == 403
    assert not StockLevel.objects.filter(item=setup.item, warehouse=setup.w2, qty_on_hand__gt=0).exists()


@pytest.mark.django_db
def test_a_third_branch_keeper_cannot_see_or_confirm_a_transfer_between_two_other_branches(setup, client_a):
    """Neither source nor destination: out of scope entirely, so 404 (not
    403 — the document's existence isn't disclosed), and nothing moves."""
    branch3 = LegalEntity.objects.create(
        tenant=setup.tenant, code="MAIN-03", name="فرع الدمام", entity_type=LegalEntity.Type.BRANCH, parent=setup.company,
    )
    _posted(client_a, setup)
    transfer = _posted(client_a, setup, kind="transfer", qty="4", to_warehouse=setup.w2)
    third_keeper = setup.user_client(branch3, email="third@tenant-a.test")

    assert third_keeper.get(f"{URL}{transfer['id']}/").status_code == 404
    assert third_keeper.get(f"{URL}incoming/").data == []
    response = third_keeper.post(f"{URL}{transfer['id']}/confirm-receipt/", {"date": "2026-06-11"}, format="json")

    assert response.status_code == 404
    assert not StockLevel.objects.filter(item=setup.item, warehouse=setup.w2, qty_on_hand__gt=0).exists()
    assert client_a.get(f"{URL}{transfer['id']}/").data["transfer_received"] is False


@pytest.mark.django_db
def test_the_destination_branch_sees_the_transfer_as_incoming_and_confirms_it(setup, client_a):
    _posted(client_a, setup)
    transfer = _posted(client_a, setup, kind="transfer", qty="4", to_warehouse=setup.w2)
    dest_keeper = setup.user_client(setup.branch2, email="dest@tenant-a.test")

    incoming = dest_keeper.get(f"{URL}incoming/")
    assert [str(row["id"]) for row in incoming.data] == [str(transfer["id"])]
    # Seeing it is not acting on the sender's side of it:
    assert dest_keeper.post(f"{URL}{transfer['id']}/reverse/", {"reason": "ليس لنا"}, format="json").status_code == 403

    response = dest_keeper.post(f"{URL}{transfer['id']}/confirm-receipt/", {"date": "2026-06-11"}, format="json")

    assert response.status_code == 200, response.content
    assert response.data["transfer_received"] is True
    assert StockLevel.objects.get(item=setup.item, warehouse=setup.w2).qty_on_hand == D("4")
    assert dest_keeper.get(f"{URL}incoming/").data == []


@pytest.mark.django_db
def test_list_filters_by_kind_status_warehouse_and_entity(setup, client_a):
    _posted(client_a, setup)
    client_a.post(URL, setup.payload(kind="issue", qty="1"), format="json")
    assert {r["kind"] for r in client_a.get(URL, {"kind": "issue"}).data["results"]} == {"issue"}
    assert {r["status"] for r in client_a.get(URL, {"status": "posted"}).data["results"]} == {"posted"}
    assert client_a.get(URL, {"warehouse": str(setup.w2.id)}).data["count"] == 0
    assert client_a.get(URL, {"legal_entity": str(setup.branch1.id)}).data["count"] == 2


@pytest.mark.django_db
def test_the_module_disabled_is_404(setup, client_a):
    setup.tenant.features.inventory = False
    setup.tenant.features.save(update_fields=["inventory"])
    assert client_a.get(URL).status_code == 404


@pytest.mark.django_db
def test_stock_moves_are_never_exposed_for_writing(setup, client_a):
    """No endpoint touches StockMove directly — only the engine writes it."""
    _posted(client_a, setup)
    assert StockMove.objects.count() == 1
    assert client_a.get("/api/stock-moves/").status_code == 404


@pytest.mark.django_db
def test_stock_levels_report_value_at_the_company_average_and_is_entity_scoped(setup, client_a):
    _posted(client_a, setup, qty="10", unit_cost="100")
    _posted(client_a, setup, qty="10", unit_cost="120", warehouse=setup.w2)  # same company, other branch

    rows = {r["warehouse_name"]: r for r in client_a.get("/api/stock-levels/").data["results"]}
    assert D(rows["مستودع الرياض"]["avg_cost"]) == D("110") and D(rows["مستودع الرياض"]["value"]) == D("1100")
    assert D(rows["مستودع جدة"]["value"]) == D("1100")

    keeper = setup.user_client(setup.branch1)
    names = [r["warehouse_name"] for r in keeper.get("/api/stock-levels/").data["results"]]
    assert names == ["مستودع الرياض"]


@pytest.mark.django_db
def test_transfer_destinations_list_the_same_company_s_other_warehouses_only(setup, client_a):
    other_company = LegalEntity.objects.create(
        tenant=setup.tenant, code="OTHER", name="شركة أخرى", entity_type=LegalEntity.Type.COMPANY,
    )
    Warehouse.objects.create(tenant=setup.tenant, legal_entity=other_company, code="WO", name="مستودع آخر")
    keeper = setup.user_client(setup.branch1)  # can't list branch2's warehouses via /warehouses/

    rows = keeper.get(f"{URL}transfer-destinations/", {"warehouse": str(setup.w1.id)}).data

    assert [r["name"] for r in rows] == ["مستودع جدة"]
