"""Sprint 7.5: count sessions (D16) — StockDocument kind=COUNT, freeze,
variance posting.

The five binding points of the block, each with its own test by name:
  (a) the variance is counted − the balance AT POSTING, and a balance that
      moved since the session opened is shown before posting (409 + drift);
  (b) a partial count never touches what it did not count;
  (c) the freeze is inside the engine (post_stock_document itself);
  (d) reversing a count restores quantities, values, the average — and the
      serials it marked disposed;
  (e) the CSV import is atomic.

Every scenario that posts ends with _assert_reconciled (Σ inventory
accounts == Σ ItemCost == Σ StockMove.value) — a count writes StockMove,
ItemCost, StockLevel, BatchStock and SerialNumber at once.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

from apps.accounting.models import JournalLine
from apps.inventory.models import (
    Batch,
    BatchStock,
    InventorySettings,
    ItemCategory,
    ItemCost,
    SerialNumber,
    StockDocument,
    StockLevel,
    StockMove,
)
from apps.inventory.services import (
    confirm_transfer_receipt,
    create_count_session,
    post_stock_document,
    reverse_stock_document,
    set_counts,
)
from apps.sales.models import Product

from .factories import ProductFactory
from .test_sprint7_block3 import _assert_cost, _assert_reconciled, _balance, _leaf_account, _World

D = Decimal
URL = "/api/stock-documents/"
DAY = date(2026, 6, 10)


@pytest.fixture
def world(tenant_a):
    tenant_a.features.inventory = True
    tenant_a.features.save(update_fields=["inventory"])
    return _World(tenant_a)


def _session(world, warehouse=None, category=None, search="", on_date=DAY):
    warehouse = warehouse or world.w1
    return create_count_session(
        world.tenant, world.user, {"legal_entity": warehouse.legal_entity, "warehouse": warehouse, "date": on_date},
        category=category, search=search,
    )


def _line(session, item, batch=None):
    return session.lines.get(item=item, batch=batch)


def _count(world, session, counts):
    """counts: {item_or_(item, batch): qty | (qty, [serial strings])}."""
    entries = []
    for row, (key, value) in enumerate(counts.items(), start=1):
        item, batch = key if isinstance(key, tuple) else (key, None)
        qty, serials = value if isinstance(value, tuple) else (value, [])
        entries.append({"row": row, "line": str(_line(session, item, batch).id), "counted_qty": qty, "serials": serials})
    set_counts(session, world.user, entries)


def _approve_and_post(world, session):
    session.status = StockDocument.Status.APPROVED
    session.save(update_fields=["status"])
    return post_stock_document(session, world.user)


def _entry_lines(document):
    return sorted(
        (line.account.system_key, line.debit, line.credit)
        for line in JournalLine.objects.filter(
            entry__content_type=ContentType.objects.get_for_model(StockDocument), entry__object_id=document.id,
        ).select_related("account")
    )


def _stock_116(world):
    """The spec's reference numbers: 25 units, 2900.00, average 116."""
    world.receipt("10", "100", DAY)
    world.receipt("10", "120", DAY)
    world.receipt("5", "140", DAY)
    _assert_cost(world.cost(), "25", "2900.00", "116.0000")


# ------------------------------------------------- the spec's reference case


@pytest.mark.django_db
def test_a_shortage_of_2_at_average_116_posts_232_dr_adjustment_cr_inventory(world):
    _stock_116(world)
    session = _session(world)
    assert _line(session, world.item).expected_qty == D("25")
    _count(world, session, {world.item: "23"})

    _approve_and_post(world, session)

    move = StockMove.objects.get(document=session)
    assert (move.qty_base, move.value, move.unit_cost) == (D("-2"), D("-232.00"), D("116.0000"))
    assert _entry_lines(session) == [("INVENTORY", D("0"), D("232.00")), ("INVENTORY_ADJUSTMENT", D("232.00"), D("0"))]
    assert world.level(world.w1) == D("23")
    _assert_cost(world.cost(), "23", "2668.00", "116.0000")
    session.refresh_from_db()
    assert session.status == StockDocument.Status.POSTED and session.number.startswith("SC-")
    _assert_reconciled(world.tenant, "count shortage −2 @116 -> 232.00 Dr ADJ / Cr INVENTORY")


@pytest.mark.django_db
def test_a_surplus_enters_at_the_average_dr_inventory_cr_adjustment(world):
    _stock_116(world)
    session = _session(world)
    _count(world, session, {world.item: "26"})

    _approve_and_post(world, session)

    assert _entry_lines(session) == [("INVENTORY", D("116.00"), D("0")), ("INVENTORY_ADJUSTMENT", D("0"), D("116.00"))]
    _assert_cost(world.cost(), "26", "3016.00", "116.0000")
    _assert_reconciled(world.tenant, "count surplus +1 @116 -> 116.00 Dr INVENTORY / Cr ADJ")


@pytest.mark.django_db
def test_a_count_on_a_warehouse_with_its_own_inventory_and_adjustment_accounts_routes_to_them(world):
    """Σ of EVERY inventory account in use == Σ ItemCost — with a warehouse
    inventory override, the INVENTORY system account alone is not it."""
    inventory = _leaf_account(world.tenant, "1409", "مخزون الرياض", "INVENTORY")
    adjustment = _leaf_account(world.tenant, "5079", "فروق جرد الرياض", "INVENTORY_ADJUSTMENT")
    world.w1.inventory_account_override = inventory
    world.w1.adjustment_account_override = adjustment
    world.w1.save(update_fields=["inventory_account_override", "adjustment_account_override"])
    _stock_116(world)
    session = _session(world)
    _count(world, session, {world.item: "23"})

    _approve_and_post(world, session)

    lines = sorted(
        (line.account.code, line.debit, line.credit)
        for line in JournalLine.objects.filter(entry__object_id=session.id).select_related("account")
    )
    assert lines == [("1409", D("0"), D("232.00")), ("5079", D("232.00"), D("0"))]
    assert _balance(world.tenant, "INVENTORY") == D("0")
    _assert_reconciled(world.tenant, "count on a warehouse with inventory 1409 / adjustment 5079 overrides")


# ------------------------------------------- (a) variance at posting + drift


@pytest.mark.django_db
def test_the_variance_is_against_the_balance_at_posting_and_the_drift_is_shown_first(world, client_a):
    """Open (snapshot 25), count 20, then an issue of 3 posts from the same
    warehouse (freeze off — the only way a balance can move under an open
    session). Posting must warn, by item, and then land the balance on
    exactly 20: variance −2 against the balance now (22), not −5 against
    the snapshot."""
    _stock_116(world)
    InventorySettings.objects.update_or_create(tenant=world.tenant, defaults={"freeze_warehouse_during_count": False})
    session = _session(world)
    _count(world, session, {world.item: "20"})
    world.issue("3", DAY)
    assert world.level(world.w1) == D("22")
    assert client_a.post(f"{URL}{session.id}/submit/").status_code == 200

    warned = client_a.post(f"{URL}{session.id}/post/", {}, format="json")

    print(f"\nDRIFT 409: {warned.data['detail']}")
    assert warned.status_code == 409, warned.content
    assert warned.data["code"] == "count_drift"
    assert "صنف اختبار" in warned.data["detail"] and "25" in warned.data["detail"] and "22" in warned.data["detail"]
    assert [(d["expected_qty"], d["current_qty"], d["drift"]) for d in warned.data["drift"]] == [("25.00", "22.00", "-3.00")]
    session.refresh_from_db()
    assert session.status == StockDocument.Status.APPROVED  # nothing posted on the warning

    posted = client_a.post(f"{URL}{session.id}/post/", {"acknowledge_drift": True}, format="json")

    assert posted.status_code == 200, posted.content
    assert world.level(world.w1) == D("20")  # exactly the count
    assert StockMove.objects.get(document=session).qty_base == D("-2")
    assert _line(session, world.item).qty_base == D("-2")
    _assert_reconciled(world.tenant, "drift: snapshot 25, issue 3, counted 20 -> variance −2, balance 20")


@pytest.mark.django_db
def test_the_variances_tab_shows_snapshot_now_counted_variance_and_value(world, client_a):
    _stock_116(world)
    session = _session(world)
    _count(world, session, {world.item: "23"})

    report = client_a.get(f"{URL}{session.id}/variances/").data

    row = report["lines"][0]
    assert (row["expected_qty"], row["current_qty"], row["counted_qty"], row["variance_qty"]) == (
        "25.00", "25.00", "23.00", "-2.00",
    )
    assert row["variance_value"] == "-232.00" and row["drift"] == "0.00"
    assert report["shortage_value"] == "232.00" and report["surplus_value"] == "0.00"


# ----------------------------------------------- (b) partial count isolation


@pytest.mark.django_db
def test_a_partial_count_by_category_moves_only_the_two_counted_items_and_leaves_the_other_three_untouched(world):
    category = ItemCategory.objects.create(tenant=world.tenant, code="C1", name="فئة الجرد")
    items = [ProductFactory(tenant=world.tenant, name=f"صنف {n}", item_type=Product.ItemType.STOCK) for n in range(5)]
    for item in items[:2]:
        item.category = category
        item.save(update_fields=["category"])
    for n, item in enumerate(items):
        world.doc(StockDocument.Kind.RECEIPT, [{"item": item, "qty": "10", "unit_cost": str(100 + n)}], DAY)

    others = items[2:]

    def snapshot():
        return {
            item.name: (
                StockLevel.objects.get(item=item, warehouse=world.w1).qty_on_hand,
                *ItemCost.objects.filter(item=item).values_list("qty_on_hand", "total_value", "avg_cost").get(),
                StockMove.objects.filter(item=item).count(),
            )
            for item in others
        }

    before = snapshot()
    session = _session(world, category=category)
    assert set(session.lines.values_list("item_id", flat=True)) == {items[0].id, items[1].id}
    _count(world, session, {items[0]: "7", items[1]: "12"})

    _approve_and_post(world, session)

    moved = sorted((m.item.name, m.qty_base) for m in StockMove.objects.filter(document=session))
    assert moved == [("صنف 0", D("-3")), ("صنف 1", D("2"))]
    after = snapshot()
    print(f"\nPARTIAL COUNT — the three outside the scope, before: {before}")
    print(f"PARTIAL COUNT — the three outside the scope, after:  {after}")
    assert after == before
    _assert_reconciled(world.tenant, "partial count on a 2-item category of a 5-item warehouse")


@pytest.mark.django_db
def test_counted_zero_is_a_real_variance_and_not_counted_is_nothing(world):
    other = ProductFactory(tenant=world.tenant, name="صنف لم يُعدّ", item_type=Product.ItemType.STOCK)
    world.receipt("4", "50", DAY)
    world.doc(StockDocument.Kind.RECEIPT, [{"item": other, "qty": "6", "unit_cost": "30"}], DAY)
    session = _session(world)
    _count(world, session, {world.item: "0"})  # `other` left blank

    _approve_and_post(world, session)

    assert world.level(world.w1) == D("0")
    assert world.level(world.w1, item=other) == D("6")
    assert not StockMove.objects.filter(document=session, item=other).exists()
    assert _line(session, other).counted_qty is None and _line(session, other).qty_base == D("0")
    _assert_reconciled(world.tenant, "counted 0 empties the item; the uncounted one is untouched")


@pytest.mark.django_db
def test_a_session_with_nothing_counted_cannot_be_submitted_or_posted(world, client_a):
    world.receipt("4", "50", DAY)
    session = _session(world)
    response = client_a.post(f"{URL}{session.id}/submit/")
    assert response.status_code == 400 and "لم يُدخَل عدّ" in response.data["detail"]
    with pytest.raises(ValidationError, match="لم يُدخَل عدّ"):
        _approve_and_post(world, session)


# ------------------------------------------------- (c) freeze in the engine


@pytest.mark.django_db
def test_posting_an_issue_on_a_frozen_warehouse_is_400_naming_the_warehouse_and_the_session(world, client_a):
    world.receipt("10", "100", DAY)
    session = _session(world)  # freeze_warehouse_during_count defaults to True
    created = client_a.post(
        URL,
        {
            "kind": "issue", "legal_entity": str(world.branch1.id), "warehouse": str(world.w1.id), "date": "2026-06-10",
            "lines": [{"item": str(world.item.id), "qty": "1"}],
        },
        format="json",
    )
    assert created.status_code == 201, created.content
    client_a.post(f"{URL}{created.data['id']}/submit/")

    response = client_a.post(f"{URL}{created.data['id']}/post/")

    print(f"\nFREEZE 400: {response.data['detail']}")
    assert response.status_code == 400
    assert "مستودع الرياض" in response.data["detail"] and "مجمَّد" in response.data["detail"]
    assert "جرد 2026-06-10" in response.data["detail"]
    assert world.level(world.w1) == D("10")
    # Deleting the session lifts the freeze.
    assert client_a.delete(f"{URL}{session.id}/").status_code == 204
    assert client_a.post(f"{URL}{created.data['id']}/post/").status_code == 200
    _assert_reconciled(world.tenant, "frozen issue refused, posted after the session was deleted")


@pytest.mark.django_db
def test_the_freeze_holds_for_a_direct_engine_call_and_for_a_transfer_receipt_into_the_warehouse(world):
    """No API in between — the path a Celery task would take."""
    world.receipt("10", "100", DAY, warehouse=world.w2)
    transfer = world.doc(StockDocument.Kind.TRANSFER, [{"qty": "2"}], DAY, warehouse=world.w2, to_warehouse=world.w1)
    world.receipt("5", "100", DAY)
    _session(world)
    issue = world.issue("1", DAY, post=False)

    with pytest.raises(ValidationError, match="مجمَّد"):
        post_stock_document(issue, world.user)
    with pytest.raises(ValidationError, match="مجمَّد"):
        confirm_transfer_receipt(transfer, world.user, date=DAY)

    InventorySettings.objects.update_or_create(tenant=world.tenant, defaults={"freeze_warehouse_during_count": False})
    post_stock_document(issue, world.user)
    _assert_reconciled(world.tenant, "freeze off -> the issue posts")


@pytest.mark.django_db
def test_one_open_session_per_warehouse_and_its_lines_are_not_editable(world, client_a):
    world.receipt("4", "50", DAY)
    session = _session(world)
    with pytest.raises(ValidationError, match="جلسة جرد مفتوحة"):
        _session(world)
    response = client_a.patch(
        f"{URL}{session.id}/", {"lines": [{"item": str(world.item.id), "qty": "1"}]}, format="json",
    )
    assert response.status_code == 400


# ---------------------------------------------------------- serials, batches


def _serial_item(world, serials):
    item = ProductFactory(tenant=world.tenant, name="جوال", item_type=Product.ItemType.STOCK, tracking="serial")
    rows = [SerialNumber.objects.create(tenant=world.tenant, item=item, serial=s) for s in serials]
    world.doc(StockDocument.Kind.RECEIPT, [{"item": item, "qty": str(len(rows)), "unit_cost": "500", "serials": rows}], DAY)
    return item, rows


@pytest.mark.django_db
def test_a_count_with_missing_serials_marks_them_disposed(world):
    item, rows = _serial_item(world, ["IMEI-1", "IMEI-2", "IMEI-3"])
    session = _session(world)
    _count(world, session, {item: ("1", ["IMEI-2"])})

    _approve_and_post(world, session)

    status = dict(SerialNumber.objects.filter(item=item).values_list("serial", "status"))
    assert status == {"IMEI-1": "disposed", "IMEI-2": "in_stock", "IMEI-3": "disposed"}
    assert sorted(s.serial for s in _line(session, item).serials.all()) == ["IMEI-1", "IMEI-3"]
    assert world.level(world.w1, item=item) == D("1")
    _assert_reconciled(world.tenant, "serial count: 2 of 3 missing -> disposed, 1000.00 to ADJ")


@pytest.mark.django_db
def test_a_serial_not_in_the_warehouse_cannot_be_counted(world):
    item, _rows = _serial_item(world, ["IMEI-1"])
    session = _session(world)
    from apps.inventory.services import CountEntryErrors

    with pytest.raises(CountEntryErrors) as exc:
        _count(world, session, {item: ("1", ["IMEI-404"])})
    assert "IMEI-404" in exc.value.errors[0]["reason"] and "إذن استلام" in exc.value.errors[0]["reason"]


@pytest.mark.django_db
def test_a_batch_count_adjusts_batch_stock_not_only_the_total(world):
    item = ProductFactory(tenant=world.tenant, name="دواء", item_type=Product.ItemType.STOCK, tracking="batch")
    batch_a = Batch.objects.create(tenant=world.tenant, item=item, number="A", expiry=date(2027, 1, 1))
    batch_b = Batch.objects.create(tenant=world.tenant, item=item, number="B", expiry=date(2027, 6, 1))
    world.doc(
        StockDocument.Kind.RECEIPT,
        [{"item": item, "qty": "5", "unit_cost": "10", "batch": batch_a},
         {"item": item, "qty": "5", "unit_cost": "10", "batch": batch_b}],
        DAY,
    )
    session = _session(world)
    assert session.lines.filter(item=item).count() == 2  # one line per batch
    _count(world, session, {(item, batch_a): "3", (item, batch_b): "5"})

    _approve_and_post(world, session)

    assert BatchStock.objects.get(batch=batch_a, warehouse=world.w1).qty == D("3")
    assert BatchStock.objects.get(batch=batch_b, warehouse=world.w1).qty == D("5")
    assert world.level(world.w1, item=item) == D("8")
    move = StockMove.objects.get(document=session)
    assert (move.batch_id, move.qty_base, move.value) == (batch_a.id, D("-2"), D("-20.00"))
    _assert_reconciled(world.tenant, "batch count: A 5->3, B unchanged")


# ---------------------------------------------------------- (d) reversal


@pytest.mark.django_db
def test_reversing_a_count_restores_qty_value_average_and_brings_disposed_serials_back_in_stock(world):
    _stock_116(world)
    phone, _rows = _serial_item(world, ["IMEI-1", "IMEI-2", "IMEI-3"])
    phone_cost = ItemCost.objects.get(item=phone)
    before = (world.level(world.w1), world.level(world.w1, item=phone))
    session = _session(world)
    _count(world, session, {world.item: "23", phone: ("1", ["IMEI-2"])})
    _approve_and_post(world, session)
    assert SerialNumber.objects.filter(item=phone, status="disposed").count() == 2
    _assert_reconciled(world.tenant, "count posted before reversal")

    reversal = reverse_stock_document(session, world.user, "عدّ خاطئ", date=DAY)

    assert reversal.kind == StockDocument.Kind.COUNT and reversal.status == StockDocument.Status.POSTED
    assert (world.level(world.w1), world.level(world.w1, item=phone)) == before
    _assert_cost(world.cost(), "25", "2900.00", "116.0000")
    _assert_cost(phone_cost, "3", "1500.00", "500.0000")
    serials = {s.serial: (s.status, s.warehouse_id) for s in SerialNumber.objects.filter(item=phone)}
    assert serials == {f"IMEI-{n}": ("in_stock", world.w1.id) for n in (1, 2, 3)}
    assert _balance(world.tenant, "INVENTORY_ADJUSTMENT") == D("0")
    session.refresh_from_db()
    assert session.status == StockDocument.Status.REVERSED
    _assert_reconciled(world.tenant, "count reversed -> 25/2900/116 and 3 phones in stock again")


@pytest.mark.django_db
def test_a_reversal_does_not_open_a_session_or_freeze_the_warehouse(world):
    _stock_116(world)
    session = _session(world)
    _count(world, session, {world.item: "24"})
    _approve_and_post(world, session)
    reverse_stock_document(session, world.user, "عدّ خاطئ", date=DAY)
    world.issue("1", DAY)  # not frozen
    _session(world)  # a new session can be opened
    _assert_reconciled(world.tenant, "after a count reversal: issue posts, new session opens")


# ------------------------------------------------------------- (e) CSV import


def _csv(client, session, text):
    return client.post(f"{URL}{session.id}/import-counts/", {"csv": text}, format="json")


@pytest.mark.django_db
def test_a_csv_with_one_invalid_row_applies_nothing_and_reports_each_row_and_reason(world, client_a):
    other = ProductFactory(tenant=world.tenant, sku="B-2", name="صنف ثان", item_type=Product.ItemType.STOCK)
    world.receipt("4", "50", DAY)
    world.doc(StockDocument.Kind.RECEIPT, [{"item": other, "qty": "6", "unit_cost": "30"}], DAY)
    session = _session(world)
    sku = world.item.sku

    response = _csv(client_a, session, f"sku,batch,counted_qty\n{sku},,3\nB-2,,abc\nNOPE,,1\n")

    print(f"\nCSV 400: {response.data}")
    assert response.status_code == 400
    assert [(e["row"], e["reason"]) for e in response.data["errors"]] == [
        (3, "الكمية «abc» ليست رقمًا صالحًا (خانتان عشريتان كحد أقصى)."),
        (4, "الصنف «NOPE» ليس ضمن أسطر هذه الجلسة."),
    ]
    assert list(session.lines.values_list("counted_qty", flat=True)) == [None, None]  # row 2 was valid: not applied

    ok = _csv(client_a, session, f"﻿sku,batch,counted_qty\n{sku},,3\nB-2,,6\n")

    assert ok.status_code == 200, ok.content
    assert {line.item_id: line.counted_qty for line in session.lines.all()} == {world.item.id: D("3"), other.id: D("6")}


@pytest.mark.django_db
def test_a_csv_import_reaches_a_posted_count_end_to_end_through_the_api(world, client_a):
    _stock_116(world)
    created = client_a.post(
        URL, {"kind": "count", "legal_entity": str(world.branch1.id), "warehouse": str(world.w1.id), "date": "2026-06-10"},
        format="json",
    )
    assert created.status_code == 201, created.content
    assert created.data["lines"][0]["expected_qty"] == "25.00"
    doc_id = created.data["id"]
    assert _csv(client_a, StockDocument.objects.get(pk=doc_id), f"sku,counted_qty\n{world.item.sku},23\n").status_code == 200
    assert client_a.post(f"{URL}{doc_id}/submit/").status_code == 200
    posted = client_a.post(f"{URL}{doc_id}/post/", {}, format="json")
    assert posted.status_code == 200, posted.content
    assert posted.data["total_value"] == "232.00" and posted.data["total_is_estimate"] is False
    _assert_reconciled(world.tenant, "count over the API: CSV -> submit -> post")


@pytest.mark.django_db
def test_counts_entered_by_hand_through_the_api_including_serials(world, client_a):
    world.receipt("10", "100", DAY)
    phone, _rows = _serial_item(world, ["IMEI-1", "IMEI-2"])
    created = client_a.post(
        URL, {"kind": "count", "legal_entity": str(world.branch1.id), "warehouse": str(world.w1.id), "date": "2026-06-10"},
        format="json",
    )
    lines = {str(line["item"]): str(line["id"]) for line in created.data["lines"]}

    response = client_a.post(
        f"{URL}{created.data['id']}/counts/",
        {"entries": [
            {"line": lines[str(world.item.id)], "counted_qty": "9"},
            {"line": lines[str(phone.id)], "serials": ["IMEI-2"]},
        ]},
        format="json",
    )

    assert response.status_code == 200, response.data
    by_item = {str(line["item"]): line for line in response.data["lines"]}
    assert by_item[str(world.item.id)]["counted_qty"] == "9.00"
    assert by_item[str(phone.id)]["counted_qty"] == "1.00"
    assert by_item[str(phone.id)]["counted_serial_numbers"] == ["IMEI-2"]
