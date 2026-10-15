"""Sprint 7.5 follow-up: one rule for a count surplus, and the refusals
that speak instead of dropping things.

  1) A surplus line carries a unit cost: the company average by default,
     editable (inventory.post) on the variance tab, recorded on the line and
     in the audit log. If the average is zero and no cost was entered, the
     posting refuses with 400 naming the item — never a zero-value surplus.
  2) The four fixed numbers of the block, each its own test.
  3) An item with no balance row in the warehouse, or a serial that is not
     there, is refused by name — no manual lines, no silent drop.

Every scenario that posts ends with _assert_reconciled, which sums
ItemCost.total_value — the value, never qty × the rounded average.
"""

from decimal import Decimal

import pytest

from apps.accounting.models import JournalLine
from apps.inventory.models import ItemCost, SerialNumber, StockDocument, StockLevel, StockMove
from apps.inventory.services import CountEntryErrors, reverse_stock_document
from apps.platform.models import AuditLog
from apps.sales.models import Product

from .factories import ProductFactory
from .test_sprint7_block3 import _assert_cost, _assert_reconciled, _World
from .test_sprint7_block5 import (
    DAY,
    URL,
    _approve_and_post,
    _count,
    _entry_lines,
    _line,
    _serial_item,
    _session,
    _stock_116,
)

D = Decimal
NOT_IN_WAREHOUSE = "غير مسجَّل في هذا المستودع — أدخله بإذن إضافة من «أذون الإضافة» ثم أعد العدّ"


@pytest.fixture
def world(tenant_a):
    tenant_a.features.inventory = True
    tenant_a.features.save(update_fields=["inventory"])
    return _World(tenant_a)


def _zero_average_item(world):
    """A stock item registered in the warehouse (a balance row, qty 0) that
    was never received at a cost — its company average is zero."""
    item = ProductFactory(tenant=world.tenant, name="صنف بلا تكلفة", sku="ZERO-1", item_type=Product.ItemType.STOCK)
    StockLevel.objects.create(tenant=world.tenant, item=item, warehouse=world.w1)
    return item


def _set_cost(client, session, item, unit_cost):
    return client.post(
        f"{URL}{session.id}/surplus-costs/",
        {"entries": [{"line": _line(session, item).id, "unit_cost": unit_cost}]},
        format="json",
    )


def _approved(session):
    session.status = StockDocument.Status.APPROVED
    session.save(update_fields=["status"])


# ------------------------------------------------------ the four fixed numbers


@pytest.mark.django_db
def test_number_1_a_surplus_of_2_at_average_116_with_no_cost_entered_posts_232(world):
    _stock_116(world)
    session = _session(world)
    _count(world, session, {world.item: "27"})

    _approve_and_post(world, session)

    move = StockMove.objects.get(document=session)
    print(f"\nNUMBER 1: move qty={move.qty_base} value={move.value} unit_cost={move.unit_cost}; entry={_entry_lines(session)}")
    assert (move.qty_base, move.value, move.unit_cost) == (D("2"), D("232.00"), D("116.0000"))
    assert _entry_lines(session) == [("INVENTORY", D("232.00"), D("0")), ("INVENTORY_ADJUSTMENT", D("0"), D("232.00"))]
    _assert_cost(world.cost(), "27", "3132.00", "116.0000")
    _assert_reconciled(world.tenant, "number 1: surplus +2 @ average 116 -> 232.00 Dr INVENTORY / Cr ADJ")


@pytest.mark.django_db
def test_number_2_a_zero_cost_surplus_is_refused_with_400_naming_the_item_and_moves_nothing(world, client_a):
    item = _zero_average_item(world)
    session = _session(world)
    _count(world, session, {item: "4"})
    _approved(session)

    response = client_a.post(f"{URL}{session.id}/post/", {}, format="json")

    print(f"\nNUMBER 2: {response.status_code} {response.data.get('detail')}")
    assert response.status_code == 400, response.content
    detail = response.data["detail"]
    assert "«صنف بلا تكلفة»" in detail and "ZERO-1" in detail
    assert "أدخل تكلفة وحدة الزيادة" in detail and "«أذون الإضافة»" in detail
    session.refresh_from_db()
    assert session.status == StockDocument.Status.APPROVED and not session.number
    assert not StockMove.objects.filter(document=session).exists()
    assert not JournalLine.objects.filter(entry__object_id=session.id).exists()
    assert StockLevel.objects.get(item=item, warehouse=world.w1).qty_on_hand == D("0")
    assert not ItemCost.objects.filter(item=item, qty_on_hand__gt=0).exists()
    assert _line(session, item).qty_base == D("0")  # the planned variance was rolled back too


@pytest.mark.django_db
def test_number_3_the_same_surplus_with_a_cost_of_25_posts_100(world, client_a):
    item = _zero_average_item(world)
    session = _session(world)
    _count(world, session, {item: "4"})
    assert _set_cost(client_a, session, item, "25").status_code == 200

    assert client_a.post(f"{URL}{session.id}/submit/").status_code == 200
    posted = client_a.post(f"{URL}{session.id}/post/", {}, format="json")

    assert posted.status_code == 200, posted.content
    move = StockMove.objects.get(document=session)
    cost = ItemCost.objects.get(item=item)
    print(f"\nNUMBER 3: move value={move.value}; ItemCost=({cost.qty_on_hand}, {cost.total_value}, {cost.avg_cost})")
    assert move.value == D("100.00")
    assert _entry_lines(session) == [("INVENTORY", D("100.00"), D("0")), ("INVENTORY_ADJUSTMENT", D("0"), D("100.00"))]
    _assert_cost(cost, "4", "100.00", "25.0000")
    _assert_reconciled(world.tenant, "number 3: surplus +4 @ entered 25 on a zero average -> 100.00")


@pytest.mark.django_db
def test_number_4_a_surplus_of_5_at_90_on_10_1000_100_keeps_the_value_1450_not_qty_times_rounded_average(
    world, client_a,
):
    world.receipt("10", "100", DAY)
    _assert_cost(world.cost(), "10", "1000.00", "100.0000")
    session = _session(world)
    _count(world, session, {world.item: "15"})
    assert _set_cost(client_a, session, world.item, "90").status_code == 200

    _approve_and_post(world, session)

    cost = world.cost()
    cost.refresh_from_db()
    print(f"\nNUMBER 4: entry={_entry_lines(session)}; ItemCost=({cost.qty_on_hand}, {cost.total_value}, {cost.avg_cost}); "
          f"15 x {cost.avg_cost} = {cost.qty_on_hand * cost.avg_cost}")
    assert _entry_lines(session) == [("INVENTORY", D("450.00"), D("0")), ("INVENTORY_ADJUSTMENT", D("0"), D("450.00"))]
    _assert_cost(cost, "15", "1450.00", "96.6667")
    # The value is the source; the average is derived from it. Re-deriving
    # the value from the rounded average would give 1450.0005.
    assert cost.qty_on_hand * cost.avg_cost == D("1450.0005") != cost.total_value
    _assert_reconciled(world.tenant, "number 4: surplus +5 @ 90 on (10, 1000, 100) -> (15, 1450.00, 96.6667)")


# ------------------------------------------------------- the surplus unit cost


@pytest.mark.django_db
def test_the_variance_tab_values_a_surplus_at_its_entered_cost_and_flags_a_zero_cost_one(world, client_a):
    _stock_116(world)
    zero = _zero_average_item(world)
    session = _session(world)
    _count(world, session, {world.item: "27", zero: "4"})

    report = client_a.get(f"{URL}{session.id}/variances/").data
    rows = {r["item_sku"]: r for r in report["lines"]}
    assert (rows[world.item.sku]["variance_value"], rows[world.item.sku]["needs_cost"]) == ("232.00", False)
    assert (rows["ZERO-1"]["variance_value"], rows["ZERO-1"]["needs_cost"]) == ("0.00", True)

    assert _set_cost(client_a, session, world.item, "120").status_code == 200
    assert _set_cost(client_a, session, zero, "25").status_code == 200
    report = client_a.get(f"{URL}{session.id}/variances/").data
    rows = {r["item_sku"]: r for r in report["lines"]}
    assert (rows[world.item.sku]["surplus_unit_cost"], rows[world.item.sku]["variance_value"]) == ("120.00", "240.00")
    assert (rows["ZERO-1"]["variance_value"], rows["ZERO-1"]["needs_cost"]) == ("100.00", False)
    assert report["surplus_value"] == "340.00"
    # The approval is judged on the same amount.
    assert client_a.get(f"{URL}{session.id}/").data["total_value"] == "340.00"


@pytest.mark.django_db
def test_a_zero_cost_surplus_cannot_be_submitted_for_approval_either(world, client_a):
    item = _zero_average_item(world)
    session = _session(world)
    _count(world, session, {item: "4"})

    response = client_a.post(f"{URL}{session.id}/submit/")

    assert response.status_code == 400
    assert "«صنف بلا تكلفة»" in response.data["detail"] and "«أذون الإضافة»" in response.data["detail"]
    session.refresh_from_db()
    assert session.status == StockDocument.Status.DRAFT


@pytest.mark.django_db
def test_the_surplus_cost_needs_inventory_post(world, client_a, user_a, tenant_a):
    from apps.access.models import Permission, Role

    _stock_116(world)
    session = _session(world)
    _count(world, session, {world.item: "27"})
    counter = Role.objects.create(tenant=tenant_a, name="Counter", is_system=False)
    counter.permissions.set(Permission.objects.filter(code__in=["inventory.view", "inventory.manage"]))
    user_a.roles.set([counter])

    assert _set_cost(client_a, session, world.item, "90").status_code == 403
    assert _line(session, world.item).surplus_unit_cost is None


@pytest.mark.django_db
def test_the_surplus_cost_is_in_the_audit_log_before_and_after_and_on_the_line(world, client_a, user_a):
    _stock_116(world)
    session = _session(world)
    _count(world, session, {world.item: "27"})

    assert _set_cost(client_a, session, world.item, "90").status_code == 200
    assert _set_cost(client_a, session, world.item, "95.50").status_code == 200
    assert _set_cost(client_a, session, world.item, "95.50").status_code == 200  # no change, no entry

    assert client_a.get(f"{URL}{session.id}/").data["lines"][0]["surplus_unit_cost"] == "95.50"
    logs = list(
        AuditLog.objects.filter(target_type="stock_document", target_id=session.id, action="stock_document.surplus_cost_set")
        .order_by("created_at")
    )
    assert [(log.before["lines"][0]["unit_cost"], log.after["lines"][0]["unit_cost"]) for log in logs] == [
        (None, "90.00"), ("90.00", "95.50"),
    ]
    assert all(log.actor_id == user_a.id and log.after["lines"][0]["sku"] == world.item.sku for log in logs)
    # The change history the screen reads.
    history = client_a.get(f"/api/audit-log/?target_type=stock_document&target_id={session.id}").data["results"]
    assert sum(1 for h in history if h["action"] == "stock_document.surplus_cost_set") == 2


@pytest.mark.django_db
def test_a_surplus_cost_must_be_positive_not_on_a_serial_line_and_only_in_a_draft(world, client_a):
    _stock_116(world)
    serial_item, _rows = _serial_item(world, ["IMEI-1"])
    session = _session(world)
    _count(world, session, {world.item: "27"})

    for bad in ("0", "-5", "abc", "1.234"):
        response = _set_cost(client_a, session, world.item, bad)
        assert response.status_code == 400 and response.data["errors"][0]["row"] == 1, bad
    response = _set_cost(client_a, session, serial_item, "10")
    assert response.status_code == 400 and "السيريال" in response.data["errors"][0]["reason"]
    assert _line(session, world.item).surplus_unit_cost is None

    assert _set_cost(client_a, session, world.item, "").status_code == 200  # clearing = back to the average
    assert client_a.post(f"{URL}{session.id}/submit/").status_code == 200
    assert _set_cost(client_a, session, world.item, "90").status_code == 409


@pytest.mark.django_db
def test_reversing_a_surplus_posted_at_an_entered_cost_restores_quantity_value_and_average(world, client_a):
    world.receipt("10", "100", DAY)
    session = _session(world)
    _count(world, session, {world.item: "15"})
    assert _set_cost(client_a, session, world.item, "90").status_code == 200
    _approve_and_post(world, session)
    _assert_cost(world.cost(), "15", "1450.00", "96.6667")

    reverse_stock_document(session, world.user, "عدّ خاطئ", date=DAY)

    _assert_cost(world.cost(), "10", "1000.00", "100.0000")
    _assert_reconciled(world.tenant, "reverse surplus @90 -> back to (10, 1000.00, 100)")


# ------------------------------------------------ refusals that name the thing


def _find(client, session, query):
    return client.post(f"{URL}{session.id}/find-item/", {"q": query}, format="json")


@pytest.mark.django_db
def test_adding_an_item_with_no_balance_row_in_the_warehouse_is_refused_by_name_and_adds_no_line(world, client_a):
    _stock_116(world)
    stranger = ProductFactory(tenant=world.tenant, name="صنف غريب", sku="NEW-9", item_type=Product.ItemType.STOCK)
    session = _session(world)
    before = session.lines.count()

    response = _find(client_a, session, "NEW-9")

    print(f"\nNO BALANCE ROW: {response.status_code} {response.data['detail']}")
    assert response.status_code == 400
    assert "«صنف غريب»" in response.data["detail"] and NOT_IN_WAREHOUSE in response.data["detail"]
    assert session.lines.count() == before
    assert not session.lines.filter(item=stranger).exists()


@pytest.mark.django_db
def test_finding_an_item_already_in_the_session_points_to_its_line(world, client_a):
    _stock_116(world)
    session = _session(world)

    response = _find(client_a, session, world.item.sku)

    assert response.status_code == 200
    assert response.data["line"] == str(_line(session, world.item).id)


@pytest.mark.django_db
def test_an_item_outside_a_partial_sessions_scope_is_refused_as_out_of_scope(world, client_a):
    _stock_116(world)
    other = ProductFactory(tenant=world.tenant, name="صنف آخر", sku="OTHER-1", item_type=Product.ItemType.STOCK)
    world.doc(StockDocument.Kind.RECEIPT, [{"item": other, "qty": "1", "unit_cost": "10"}], DAY)
    session = _session(world, search=world.item.sku)

    response = _find(client_a, session, "OTHER-1")

    assert response.status_code == 400 and "خارج نطاق هذه الجلسة" in response.data["detail"]


@pytest.mark.django_db
def test_a_serial_not_in_the_warehouse_is_refused_naming_the_serial(world, client_a):
    item, _rows = _serial_item(world, ["IMEI-1"])
    SerialNumber.objects.create(tenant=world.tenant, item=item, serial="IMEI-ELSEWHERE")  # not in stock anywhere
    session = _session(world)

    found = _find(client_a, session, "IMEI-1")
    elsewhere = _find(client_a, session, "IMEI-ELSEWHERE")
    unknown = _find(client_a, session, "IMEI-404")

    print(f"\nSERIAL: {elsewhere.data['detail']} | {unknown.data['detail']}")
    assert found.status_code == 200 and found.data["line"] == str(_line(session, item).id)
    assert elsewhere.status_code == 400
    assert "IMEI-ELSEWHERE" in elsewhere.data["detail"] and NOT_IN_WAREHOUSE in elsewhere.data["detail"]
    assert unknown.status_code == 400
    assert "IMEI-404" in unknown.data["detail"] and NOT_IN_WAREHOUSE in unknown.data["detail"]


@pytest.mark.django_db
def test_counting_a_serial_not_in_the_warehouse_names_it_and_one_of_another_item_names_both(world):
    phone, _ = _serial_item(world, ["IMEI-1", "IMEI-2"])
    tablet = ProductFactory(tenant=world.tenant, name="لوحي", item_type=Product.ItemType.STOCK, tracking="serial")
    tab_serial = SerialNumber.objects.create(tenant=world.tenant, item=tablet, serial="TAB-1")
    world.doc(StockDocument.Kind.RECEIPT, [{"item": tablet, "qty": "1", "unit_cost": "300", "serials": [tab_serial]}], DAY)
    session = _session(world)

    with pytest.raises(CountEntryErrors) as exc:
        _count(world, session, {phone: ("3", ["IMEI-1", "IMEI-404", "TAB-1"])})

    reason = exc.value.errors[0]["reason"]
    print(f"\nSERIAL COUNT: {reason}")
    assert "IMEI-404" in reason and NOT_IN_WAREHOUSE in reason
    assert "TAB-1" in reason and "«لوحي»" in reason
    assert _line(session, phone).counted_qty is None
