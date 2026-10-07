"""Sprint 7.2.6 (docs/prompts/sprint-7.md §8.2, D5): StockDocument/
StockDocumentLine, numbering, and reversal — no posting/stock-movement
engine here (that's 7.3). The tests this block's own plan names
explicitly: a posted document can't be modified (ORM guard), numbering
assigns the real SR/SI/ST/SC number, and reversal creates a linked
opposite document.

Posted-immutability moved from a Python save()/delete() override to a
Postgres trigger (protect_posted_stock_document, migration 0006) after
the owner's review showed the override is silently bypassed by
QuerySet.update()/.delete() and bulk_create()/bulk_update() — none of
which call a model instance's own save()/delete(). The
test_*_is_rejected_by_the_database tests below exercise exactly those
bypass paths against the real trigger, mirroring
tests/test_db_triggers.py's own pattern for JournalEntry/JournalLine
(transaction=True, django.db.DatabaseError, a fresh Tenant/LegalEntity
per test rather than the tenant_a fixture — tenant_a depends on the
plain `db` fixture, which pytest-django refuses to mix with the
`transactional_db` fixture `transaction=True` implies).
"""

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction

from apps.inventory.models import StockDocument, StockDocumentLine, Warehouse
from apps.inventory.services import post_stock_document, reverse_stock_document
from apps.organization.models import LegalEntity

from .factories import LegalEntityFactory, ProductFactory, TenantFactory, UserFactory


def _make_warehouse(tenant):
    entity = LegalEntity.objects.get(tenant=tenant, code="MAIN-01")
    return entity, Warehouse.objects.create(tenant=tenant, legal_entity=entity, code="W1", name="مستودع")


def _make_document(tenant, user, entity, warehouse, kind=StockDocument.Kind.RECEIPT, status=StockDocument.Status.DRAFT):
    return StockDocument.objects.create(
        tenant=tenant, legal_entity=entity, warehouse=warehouse, kind=kind,
        date=date(2026, 6, 15), created_by=user, status=status,
    )


def _posted_document_with_line(item_qty=Decimal("10"), unit_cost=Decimal("0")):
    """Fresh tenant/entity/warehouse/user/item — never the tenant_a
    fixture, see this module's own docstring for why — with one posted
    document carrying one line, for the trigger tests below."""
    tenant = TenantFactory()
    entity = LegalEntityFactory(tenant=tenant)
    warehouse = Warehouse.objects.create(tenant=tenant, legal_entity=entity, code="W1", name="مستودع")
    user = UserFactory(tenant=tenant)
    item = ProductFactory(tenant=tenant)
    document = _make_document(tenant, user, entity, warehouse, status=StockDocument.Status.DRAFT)
    line = StockDocumentLine.objects.create(
        document=document, item=item, qty=item_qty, qty_base=item_qty, unit_cost=unit_cost,
    )
    document.status = StockDocument.Status.APPROVED
    document.save(update_fields=["status"])
    post_stock_document(document, user)
    document.refresh_from_db()
    return tenant, user, item, document, line


@pytest.mark.django_db(transaction=True)
def test_direct_update_of_a_posted_stock_document_is_rejected_by_the_database():
    _, _, _, document, _ = _posted_document_with_line()
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            StockDocument.objects.filter(pk=document.pk).update(reference="tampered")


@pytest.mark.django_db(transaction=True)
def test_direct_delete_of_a_posted_stock_document_is_rejected_by_the_database():
    _, _, _, document, _ = _posted_document_with_line()
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            StockDocument.objects.filter(pk=document.pk).delete()


@pytest.mark.django_db(transaction=True)
def test_bulk_update_of_a_posted_stock_document_is_rejected_by_the_database():
    _, _, _, document, _ = _posted_document_with_line()
    document.reference = "tampered via bulk_update"
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            StockDocument.objects.bulk_update([document], ["reference"])


@pytest.mark.django_db(transaction=True)
def test_direct_update_of_a_line_on_a_posted_stock_document_is_rejected_by_the_database():
    _, _, _, _, line = _posted_document_with_line()
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            StockDocumentLine.objects.filter(pk=line.pk).update(qty=Decimal("999"))


@pytest.mark.django_db(transaction=True)
def test_direct_delete_of_a_line_on_a_posted_stock_document_is_rejected_by_the_database():
    _, _, _, _, line = _posted_document_with_line()
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            StockDocumentLine.objects.filter(pk=line.pk).delete()


@pytest.mark.django_db(transaction=True)
def test_bulk_create_of_a_new_line_onto_a_posted_stock_document_is_rejected_by_the_database():
    _, _, item, document, _ = _posted_document_with_line()
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            StockDocumentLine.objects.bulk_create(
                [StockDocumentLine(document=document, item=item, qty=Decimal("1"), qty_base=Decimal("1"))]
            )


@pytest.mark.django_db(transaction=True)
def test_bulk_update_of_a_line_on_a_posted_stock_document_is_rejected_by_the_database():
    _, _, _, _, line = _posted_document_with_line()
    line.qty = Decimal("999")
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            StockDocumentLine.objects.bulk_update([line], ["qty"])


@pytest.mark.django_db(transaction=True)
def test_the_one_allowed_transition_posted_to_reversed_still_works_via_the_orm():
    """Confirms the trigger's exception list isn't overbroad — the
    application's own reverse path must keep working exactly as
    before, same check test_db_triggers.py makes for JournalEntry."""
    _, user, _, document, _ = _posted_document_with_line()
    reversal = reverse_stock_document(document, user, "trigger test reversal")
    assert reversal.status == StockDocument.Status.POSTED
    document.refresh_from_db()
    assert document.status == StockDocument.Status.REVERSED


@pytest.mark.django_db
def test_serials_association_on_a_posted_line_is_a_known_accepted_gap(tenant_a):
    """Documents, rather than silently hides, the one bypass path the
    trigger deliberately does not close (see StockDocumentLine's own
    docstring for why) — proven with a real write, not just claimed in
    a comment: adding a serial to an already-posted line's M2M does
    NOT raise."""
    from apps.inventory.models import SerialNumber

    user = UserFactory(tenant=tenant_a)
    entity, warehouse = _make_warehouse(tenant_a)
    item = ProductFactory(tenant=tenant_a)
    document = _make_document(tenant_a, user, entity, warehouse, status=StockDocument.Status.DRAFT)
    line = StockDocumentLine.objects.create(document=document, item=item, qty=Decimal("1"), qty_base=Decimal("1"))
    document.status = StockDocument.Status.APPROVED
    document.save(update_fields=["status"])
    post_stock_document(document, user)

    serial = SerialNumber.objects.create(tenant=tenant_a, item=item, serial="KNOWN-GAP-001")
    line.serials.add(serial)  # must NOT raise — this is the accepted, documented gap
    assert serial in line.serials.all()


@pytest.mark.django_db
def test_post_stock_document_assigns_the_real_number_for_its_kind(tenant_a):
    user = UserFactory(tenant=tenant_a)
    entity, warehouse = _make_warehouse(tenant_a)
    receipt = _make_document(tenant_a, user, entity, warehouse, kind=StockDocument.Kind.RECEIPT, status=StockDocument.Status.APPROVED)
    issue = _make_document(tenant_a, user, entity, warehouse, kind=StockDocument.Kind.ISSUE, status=StockDocument.Status.APPROVED)

    post_stock_document(receipt, user)
    post_stock_document(issue, user)

    assert receipt.number.startswith("SR-")
    assert issue.number.startswith("SI-")


@pytest.mark.django_db
def test_post_stock_document_rejects_a_draft_document(tenant_a):
    user = UserFactory(tenant=tenant_a)
    entity, warehouse = _make_warehouse(tenant_a)
    document = _make_document(tenant_a, user, entity, warehouse, status=StockDocument.Status.DRAFT)

    with pytest.raises(ValidationError):
        post_stock_document(document, user)


@pytest.mark.django_db
def test_reverse_stock_document_creates_a_linked_opposite_document(tenant_a):
    user = UserFactory(tenant=tenant_a)
    entity, warehouse = _make_warehouse(tenant_a)
    item = ProductFactory(tenant=tenant_a)
    document = _make_document(tenant_a, user, entity, warehouse, status=StockDocument.Status.DRAFT)
    StockDocumentLine.objects.create(
        document=document, item=item, qty=Decimal("10"), qty_base=Decimal("10"), unit_cost=Decimal("25.50"),
    )
    document.status = StockDocument.Status.APPROVED
    document.save(update_fields=["status"])
    post_stock_document(document, user)

    reversal = reverse_stock_document(document, user, "تصحيح كمية خاطئة")

    document.refresh_from_db()
    assert document.status == StockDocument.Status.REVERSED
    assert reversal.status == StockDocument.Status.POSTED
    assert reversal.reverses_id == document.id
    assert reversal.kind == document.kind

    reversed_line = reversal.lines.get()
    assert reversed_line.qty == Decimal("-10")
    assert reversed_line.qty_base == Decimal("-10")
    assert reversed_line.unit_cost == Decimal("25.50")  # the ORIGINAL line's own recorded cost, not re-derived


@pytest.mark.django_db
def test_reverse_stock_document_rejects_a_document_that_is_not_posted(tenant_a):
    user = UserFactory(tenant=tenant_a)
    entity, warehouse = _make_warehouse(tenant_a)
    document = _make_document(tenant_a, user, entity, warehouse, status=StockDocument.Status.DRAFT)

    with pytest.raises(ValidationError):
        reverse_stock_document(document, user, "reason")


@pytest.mark.django_db
def test_reverse_journal_entry_rejects_a_stock_document_sourced_entry(tenant_a):
    from django.contrib.contenttypes.models import ContentType

    from apps.accounting.models import JournalEntry
    from apps.accounting.services import StockDocumentReversalRejected, reverse_journal_entry

    user = UserFactory(tenant=tenant_a)
    entity, warehouse = _make_warehouse(tenant_a)
    document = _make_document(tenant_a, user, entity, warehouse, status=StockDocument.Status.APPROVED)
    post_stock_document(document, user)

    entry = JournalEntry.objects.create(
        tenant=tenant_a, legal_entity=entity, date=document.date, memo="stub stock posting",
        number="JV-2026-STUB", status=JournalEntry.Status.POSTED,
        content_type=ContentType.objects.get_for_model(StockDocument), object_id=document.id,
        # No "stock_document" ProducedBy member exists yet — 7.3's own
        # engine isn't built (this test stubs its future output ahead
        # of time). This test's own assertion is gated by content_type,
        # not produced_by, so MANUAL here is inert, not a claim.
        produced_by=JournalEntry.ProducedBy.MANUAL,
    )

    with pytest.raises(StockDocumentReversalRejected):
        reverse_journal_entry(entry, user, "trying to bypass the document-level reversal")
