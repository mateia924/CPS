"""Sprint 7.3: the stock move engine — StockMove, moving weighted
average per COMPANY (D2), post/reverse/transfer-receipt services.

Every scenario ends with _assert_reconciled: the INVENTORY account's
balance in the ledger must equal Σ ItemCost.total_value. If those two
ever disagree, the engine is misreporting the balance sheet.

There are no stock-document endpoints in this block (no screens), so
the "400" cases are asserted as django ValidationError at the service
layer — the exception every view in this project maps to 400. The
409 case goes through the real /api/journal-entries/{id}/reverse/.
"""

import threading
import time
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.models import Sum

from apps.accounting.models import Account, JournalEntry, JournalLine
from apps.accounting.services import (
    REPORTABLE_STATUSES,
    StockDocumentReversalRejected,
    reverse_journal_entry,
)
from apps.inventory import services as inventory_services
from apps.inventory.models import (
    Batch,
    BatchStock,
    InventorySettings,
    ItemCategory,
    ItemCost,
    SerialNumber,
    StockDocument,
    StockDocumentLine,
    StockLevel,
    StockMove,
    Warehouse,
)
from apps.inventory.services import (
    confirm_transfer_receipt,
    post_stock_document,
    reverse_stock_document,
)
from apps.organization.models import LegalEntity
from apps.sales.models import Product

from .factories import ProductFactory, UserFactory

D = Decimal


# ---------------------------------------------------------------- helpers


class _World:
    def __init__(self, tenant):
        self.tenant = tenant
        self.user = UserFactory(tenant=tenant)
        self.company = LegalEntity.objects.get(tenant=tenant, code="MAIN")
        self.branch1 = LegalEntity.objects.get(tenant=tenant, code="MAIN-01")
        self.branch2 = LegalEntity.objects.create(
            tenant=tenant, code="MAIN-02", name="فرع ٢", entity_type=LegalEntity.Type.BRANCH,
            parent=self.company,
        )
        self.w1 = Warehouse.objects.create(tenant=tenant, legal_entity=self.branch1, code="W1", name="مستودع الرياض")
        self.w2 = Warehouse.objects.create(tenant=tenant, legal_entity=self.branch2, code="W2", name="مستودع جدة")
        self.item = ProductFactory(tenant=tenant, name="صنف اختبار", item_type=Product.ItemType.STOCK)

    def doc(self, kind, lines, on_date, warehouse=None, to_warehouse=None, post=True):
        warehouse = warehouse or self.w1
        document = StockDocument.objects.create(
            tenant=self.tenant, legal_entity=warehouse.legal_entity, warehouse=warehouse,
            to_warehouse=to_warehouse, kind=kind, date=on_date, created_by=self.user,
            status=StockDocument.Status.APPROVED,
        )
        for spec in lines:
            spec = dict(spec)
            serials = spec.pop("serials", [])
            qty = D(spec.pop("qty"))
            line = StockDocumentLine.objects.create(
                document=document, item=spec.pop("item", self.item), qty=qty, qty_base=qty,
                unit_cost=D(spec.pop("unit_cost", "0")), **spec,
            )
            if serials:
                line.serials.set(serials)
        if post:
            post_stock_document(document, self.user)
        return document

    def receipt(self, qty, unit_cost, on_date, **kw):
        return self.doc(StockDocument.Kind.RECEIPT, [{"qty": qty, "unit_cost": unit_cost}], on_date, **kw)

    def issue(self, qty, on_date, **kw):
        return self.doc(StockDocument.Kind.ISSUE, [{"qty": qty}], on_date, **kw)

    def cost(self, item=None):
        return ItemCost.objects.get(item=item or self.item, company_entity=self.company)

    def level(self, warehouse, item=None):
        return StockLevel.objects.get(item=item or self.item, warehouse=warehouse).qty_on_hand


def _balance(tenant, system_key=None, account=None, legal_entity=None):
    lines = JournalLine.objects.filter(entry__tenant=tenant, entry__status__in=REPORTABLE_STATUSES)
    lines = lines.filter(account=account) if account is not None else lines.filter(account__system_key=system_key)
    if legal_entity is not None:
        lines = lines.filter(entry__legal_entity=legal_entity)
    totals = lines.aggregate(debit=Sum("debit"), credit=Sum("credit"))
    return (totals["debit"] or D("0")) - (totals["credit"] or D("0"))


def _inventory_accounts(tenant):
    """Every account that can hold inventory value in this tenant — the
    INVENTORY system account plus every warehouse/item/category inventory
    override. Derived from the data, deliberately NOT from the engine's own
    _inventory_account resolver: a routing bug must not be able to agree
    with itself here."""
    ids = {Account.objects.get(tenant=tenant, system_key="INVENTORY").id}
    for model, field_name in (
        (Warehouse, "inventory_account_override"),
        (Product, "inventory_account_override"),
        (ItemCategory, "default_inventory_account"),
    ):
        ids |= set(
            model.objects.filter(tenant=tenant, **{f"{field_name}__isnull": False}).values_list(f"{field_name}_id", flat=True)
        )
    return Account.objects.filter(id__in=ids).order_by("code")


def _assert_reconciled(tenant, scenario):
    """Σ of every inventory account in the ledger == Σ ItemCost.total_value
    == Σ StockMove.value. Not "the INVENTORY system account == Σ ItemCost":
    with an inventory-account override in play, that narrower form is false
    by design."""
    per_account = {acc.code: _balance(tenant, account=acc) for acc in _inventory_accounts(tenant)}
    ledger = sum(per_account.values(), D("0"))
    item_costs = ItemCost.objects.filter(tenant=tenant).aggregate(v=Sum("total_value"))["v"] or D("0")
    moves = StockMove.objects.filter(tenant=tenant).aggregate(v=Sum("value"))["v"] or D("0")
    breakdown = " + ".join(f"{code}:{amount}" for code, amount in per_account.items())
    print(f"\nRECONCILE [{scenario}]: Σinventory accounts={ledger} ({breakdown}) ΣItemCost={item_costs} ΣStockMove.value={moves}")
    assert ledger == item_costs == moves, scenario


def _assert_cost(cost, qty, value, avg):
    cost.refresh_from_db()
    assert (cost.qty_on_hand, cost.total_value, cost.avg_cost) == (D(qty), D(value), D(avg))


@pytest.fixture
def world(tenant_a):
    return _World(tenant_a)


# ------------------------------------------------- moving weighted average


@pytest.mark.django_db
def test_moving_weighted_average_with_the_fixed_reference_numbers(world):
    world.receipt("10", "100", date(2026, 6, 1))
    _assert_reconciled(world.tenant, "receipt 10@100")
    world.receipt("10", "120", date(2026, 6, 2))
    _assert_reconciled(world.tenant, "receipt 10@120")
    world.receipt("5", "140", date(2026, 6, 3))
    _assert_cost(world.cost(), "25", "2900.00", "116.0000")
    _assert_reconciled(world.tenant, "receipt 5@140 -> 25 / 2900.00 / 116")

    issue = world.issue("8", date(2026, 6, 4))
    move = StockMove.objects.get(document=issue)
    assert move.qty_base == D("-8")
    assert move.value == D("-928.00")
    assert move.unit_cost == D("116.00")
    assert issue.lines.get().unit_cost == D("116.00")  # fixed on the line at posting time
    assert _balance(world.tenant, "COGS") == D("928.00")
    _assert_cost(world.cost(), "17", "1972.00", "116.0000")
    _assert_reconciled(world.tenant, "issue 8 -> cost 928.00, 17 / 1972.00 / 116")

    world.receipt("3", "150", date(2026, 6, 5))
    _assert_cost(world.cost(), "20", "2422.00", "121.1000")
    assert world.level(world.w1) == D("20")
    _assert_reconciled(world.tenant, "receipt 3@150 -> 20 / 2422.00 / 121.1")


@pytest.mark.django_db
def test_issue_beyond_available_is_rejected_naming_item_warehouse_and_available_qty(world):
    world.receipt("8", "100", date(2026, 6, 1))
    document = world.issue("9", date(2026, 6, 2), post=False)

    with pytest.raises(ValidationError) as exc:
        post_stock_document(document, world.user)

    message = exc.value.messages[0]
    assert "صنف اختبار" in message
    assert "مستودع الرياض" in message
    assert "8" in message and "9" in message
    document.refresh_from_db()
    assert document.status == StockDocument.Status.APPROVED
    assert not StockMove.objects.filter(document=document).exists()
    _assert_cost(world.cost(), "8", "800.00", "100.0000")
    _assert_reconciled(world.tenant, "rejected issue 9 of 8 — nothing moved")


@pytest.mark.django_db
def test_posting_dated_before_the_items_last_move_in_the_company_is_rejected(world):
    world.receipt("10", "100", date(2026, 6, 15))
    # A different branch of the SAME company — the rule is per company.
    document = world.receipt("5", "100", date(2026, 6, 10), warehouse=world.w2, post=False)

    with pytest.raises(ValidationError) as exc:
        post_stock_document(document, world.user)

    assert "2026-06-15" in exc.value.messages[0]
    # Same date as the last move is allowed.
    world.receipt("5", "100", date(2026, 6, 15), warehouse=world.w2)
    _assert_reconciled(world.tenant, "backdated receipt rejected, same-date accepted")


@pytest.mark.django_db
def test_rounding_residue_is_zeroed_when_the_quantity_reaches_zero(world):
    world.receipt("1", "10.00", date(2026, 6, 1))
    world.receipt("2", "10.01", date(2026, 6, 1))  # 3 units worth 30.02
    for _ in range(3):
        world.issue("1", date(2026, 6, 2))
    _assert_cost(world.cost(), "0", "0.00", "10.00")  # last average carried; value exactly 0
    assert _balance(world.tenant, "COGS") == D("30.02")
    _assert_reconciled(world.tenant, "three single issues of 3 units worth 30.02")


# --------------------------------------------------------------- transfer


@pytest.mark.django_db
def test_transfer_between_branches_of_one_company_keeps_the_average_and_parks_value_in_transit(world):
    world.receipt("10", "100", date(2026, 6, 1))
    world.receipt("10", "120", date(2026, 6, 1))
    _assert_cost(world.cost(), "20", "2200.00", "110.0000")

    transfer = world.doc(
        StockDocument.Kind.TRANSFER, [{"qty": "5"}], date(2026, 6, 2), warehouse=world.w1, to_warehouse=world.w2,
    )
    assert world.level(world.w1) == D("15")
    assert not StockLevel.objects.filter(item=world.item, warehouse=world.w2, qty_on_hand__gt=0).exists()
    assert _balance(world.tenant, "GOODS_IN_TRANSIT") == D("550.00")
    _assert_cost(world.cost(), "15", "1650.00", "110.0000")
    _assert_reconciled(world.tenant, "transfer out 5 — 550.00 in GOODS_IN_TRANSIT")

    confirm_transfer_receipt(transfer, world.user, date=date(2026, 6, 3))
    assert world.level(world.w2) == D("5")
    assert _balance(world.tenant, "GOODS_IN_TRANSIT") == D("0")
    _assert_cost(world.cost(), "20", "2200.00", "110.0000")
    _assert_reconciled(world.tenant, "transfer receipt confirmed — GIT back to 0")

    with pytest.raises(ValidationError):
        confirm_transfer_receipt(transfer, world.user, date=date(2026, 6, 3))
    with pytest.raises(ValidationError):
        reverse_stock_document(transfer, world.user, "late", date=date(2026, 6, 3))


@pytest.mark.django_db
def test_reversing_an_unreceived_transfer_returns_goods_from_transit(world):
    world.receipt("10", "100", date(2026, 6, 1))
    transfer = world.doc(
        StockDocument.Kind.TRANSFER, [{"qty": "4"}], date(2026, 6, 2), warehouse=world.w1, to_warehouse=world.w2,
    )
    reverse_stock_document(transfer, world.user, "خطأ", date=date(2026, 6, 2))

    assert world.level(world.w1) == D("10")
    assert _balance(world.tenant, "GOODS_IN_TRANSIT") == D("0")
    _assert_cost(world.cost(), "10", "1000.00", "100.0000")
    _assert_reconciled(world.tenant, "unreceived transfer reversed")
    with pytest.raises(ValidationError):
        confirm_transfer_receipt(transfer, world.user, date=date(2026, 6, 3))


# --------------------------------------------------------------- reversal


@pytest.mark.django_db
def test_reversing_the_last_receipt_restores_qty_value_and_average(world):
    world.receipt("10", "100", date(2026, 6, 1))
    world.receipt("10", "120", date(2026, 6, 2))
    world.receipt("5", "140", date(2026, 6, 3))
    world.issue("8", date(2026, 6, 4))
    last = world.receipt("3", "150", date(2026, 6, 5))
    _assert_cost(world.cost(), "20", "2422.00", "121.1000")

    reversal = reverse_stock_document(last, world.user, "إدخال خاطئ", date=date(2026, 6, 5))

    last.refresh_from_db()
    assert last.status == StockDocument.Status.REVERSED
    assert reversal.status == StockDocument.Status.POSTED and reversal.reverses_id == last.id
    assert StockMove.objects.get(document=reversal).value == D("-450.00")
    _assert_cost(world.cost(), "17", "1972.00", "116.0000")
    assert world.level(world.w1) == D("17")
    _assert_reconciled(world.tenant, "reverse receipt 3@150 -> back to 17 / 1972.00 / 116")


@pytest.mark.django_db
def test_reversing_the_last_issue_restores_qty_value_and_average(world):
    world.receipt("10", "100", date(2026, 6, 1))
    world.receipt("10", "120", date(2026, 6, 2))
    world.receipt("5", "140", date(2026, 6, 3))
    issue = world.issue("8", date(2026, 6, 4))

    reverse_stock_document(issue, world.user, "صرف خاطئ", date=date(2026, 6, 4))

    _assert_cost(world.cost(), "25", "2900.00", "116.0000")
    assert _balance(world.tenant, "COGS") == D("0")
    _assert_reconciled(world.tenant, "reverse issue 8 -> back to 25 / 2900.00 / 116")


# --------------------------------------------------- reversal guard (409)


def _stock_entry(world):
    document = world.receipt("2", "50", date(2026, 6, 1))
    return JournalEntry.objects.get(
        content_type=ContentType.objects.get_for_model(StockDocument), object_id=document.id,
    )


@pytest.mark.django_db
def test_reverse_journal_entry_on_a_stock_document_entry_is_rejected_by_the_service(world):
    entry = _stock_entry(world)
    with pytest.raises(StockDocumentReversalRejected) as exc:
        reverse_journal_entry(entry, world.user, "محاولة عكس من القيد", date=date(2026, 6, 2))
    assert "من المستند" in str(exc.value)
    entry.refresh_from_db()
    assert entry.status == JournalEntry.Status.POSTED


@pytest.mark.django_db
def test_reverse_journal_entry_api_on_a_stock_document_entry_returns_409(tenant_a, user_a, client_a):
    world = _World(tenant_a)
    entry = _stock_entry(world)

    response = client_a.post(f"/api/journal-entries/{entry.id}/reverse/", {"reason": "test"}, format="json")

    assert response.status_code == 409, response.content
    assert "من المستند" in response.json()["detail"]


# ---------------------------------------------------- StockMove immutable


@pytest.mark.django_db
def test_modifying_a_posted_stock_move_is_rejected(world):
    document = world.receipt("10", "100", date(2026, 6, 1))
    move = StockMove.objects.get(document=document)

    move.value = D("1.00")
    with pytest.raises(ValidationError) as exc:
        move.save()
    assert "لا تُعدَّل" in exc.value.messages[0]
    with pytest.raises(ValidationError):
        move.delete()
    with pytest.raises(ValidationError):
        StockMove.objects.filter(pk=move.pk).update(value=D("1.00"))
    with pytest.raises(ValidationError):
        StockMove.objects.filter(pk=move.pk).delete()
    assert StockMove.objects.get(pk=move.pk).value == D("1000.00")


# ------------------------------------------------------- batch / serial


@pytest.mark.django_db
def test_batch_availability_is_checked_per_batch(world):
    item = ProductFactory(tenant=world.tenant, name="دواء", item_type=Product.ItemType.STOCK, tracking="batch")
    batch_a = Batch.objects.create(tenant=world.tenant, item=item, number="A1")
    batch_b = Batch.objects.create(tenant=world.tenant, item=item, number="B1")
    world.doc(StockDocument.Kind.RECEIPT, [{"item": item, "qty": "5", "unit_cost": "10", "batch": batch_a}], date(2026, 6, 1))
    world.doc(StockDocument.Kind.RECEIPT, [{"item": item, "qty": "5", "unit_cost": "10", "batch": batch_b}], date(2026, 6, 1))

    document = world.doc(
        StockDocument.Kind.ISSUE, [{"item": item, "qty": "6", "batch": batch_a}], date(2026, 6, 2), post=False,
    )
    with pytest.raises(ValidationError) as exc:
        post_stock_document(document, world.user)
    assert "A1" in exc.value.messages[0] and "5" in exc.value.messages[0]

    world.doc(StockDocument.Kind.ISSUE, [{"item": item, "qty": "5", "batch": batch_a}], date(2026, 6, 2))
    assert BatchStock.objects.get(batch=batch_a, warehouse=world.w1).qty == D("0")
    assert BatchStock.objects.get(batch=batch_b, warehouse=world.w1).qty == D("5")
    _assert_reconciled(world.tenant, "batch-tracked receipts/issue")


@pytest.mark.django_db
def test_serial_must_be_in_the_issuing_warehouse(world):
    item = ProductFactory(tenant=world.tenant, name="جوال", item_type=Product.ItemType.STOCK, tracking="serial")
    s1 = SerialNumber.objects.create(tenant=world.tenant, item=item, serial="IMEI-1")
    s2 = SerialNumber.objects.create(tenant=world.tenant, item=item, serial="IMEI-2")
    world.doc(
        StockDocument.Kind.RECEIPT, [{"item": item, "qty": "1", "unit_cost": "900", "serials": [s1]}],
        date(2026, 6, 1), warehouse=world.w2,
    )
    s1.refresh_from_db()
    assert (s1.status, s1.warehouse_id) == (SerialNumber.Status.IN_STOCK, world.w2.id)

    world.doc(StockDocument.Kind.RECEIPT, [{"item": item, "qty": "1", "unit_cost": "900", "serials": [s2]}], date(2026, 6, 1))
    document = world.doc(
        StockDocument.Kind.ISSUE, [{"item": item, "qty": "1", "serials": [s1]}], date(2026, 6, 2), post=False,
    )
    with pytest.raises(ValidationError) as exc:
        post_stock_document(document, world.user)  # IMEI-1 is in W2, the issue is from W1
    assert "IMEI-1" in exc.value.messages[0]

    issue = world.doc(StockDocument.Kind.ISSUE, [{"item": item, "qty": "1", "serials": [s2]}], date(2026, 6, 2))
    s2.refresh_from_db()
    assert (s2.status, s2.issued_doc) == (SerialNumber.Status.ISSUED, issue.id)
    assert StockMove.objects.get(document=issue).serial_id == s2.id
    _assert_reconciled(world.tenant, "serial-tracked receipts/issue")


@pytest.mark.django_db
def test_allow_negative_stock_setting_lets_an_issue_through(world):
    InventorySettings.objects.create(tenant=world.tenant, allow_negative_stock=True)
    world.receipt("2", "100", date(2026, 6, 1))
    world.issue("3", date(2026, 6, 2))
    assert world.level(world.w1) == D("-1")
    _assert_reconciled(world.tenant, "negative stock allowed")


# ------------------------------------------------------------ concurrency


@pytest.mark.django_db(transaction=True)
def test_two_concurrent_postings_on_the_same_item_lose_no_update(monkeypatch):
    """Real threads, real connections, real row locks. The first
    receipt is posted alone so ItemCost/StockLevel rows already exist
    (otherwise the unique-index wait on INSERT .. ON CONFLICT would
    serialize the two threads by itself and hide whether the FOR UPDATE
    locks do anything). Each thread then sleeps 0.5s while holding its
    locks — wide enough that without the locks both threads would read
    the same starting average and one update would be lost."""
    from apps.accounting.periods import seed_fiscal_year_for_tenant
    from apps.accounting.services import seed_chart_of_accounts
    from apps.organization.services import create_default_legal_entities

    from .factories import TenantFactory

    tenant = TenantFactory(subdomain="concurrency")
    create_default_legal_entities(tenant, tenant.name)
    seed_chart_of_accounts(tenant)
    seed_fiscal_year_for_tenant(tenant, start_date=date(2026, 1, 1))
    world = _World(tenant)
    world.receipt("10", "100", date(2026, 6, 1))
    docs = [
        world.receipt("10", "120", date(2026, 6, 2), post=False),
        world.receipt("10", "140", date(2026, 6, 2), post=False),
    ]

    original_lock = inventory_services._lock_balances
    timeline = []

    def slow_lock(*args, **kwargs):
        result = original_lock(*args, **kwargs)
        timeline.append(("locked", threading.current_thread().name, time.monotonic()))
        time.sleep(0.5)
        return result

    monkeypatch.setattr(inventory_services, "_lock_balances", slow_lock)
    barrier = threading.Barrier(2)
    errors = []

    def run(document):
        try:
            barrier.wait()
            post_stock_document(document, world.user)
        except Exception as exc:  # noqa: BLE001 — surfaced via `errors` below
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=(d,), name=f"T{i}") for i, d in enumerate(docs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, errors
    gap = abs(timeline[1][2] - timeline[0][2])
    print(f"\nCONCURRENCY: lock acquired by {timeline[0][1]} then {timeline[1][1]}, {gap:.2f}s apart")
    _assert_cost(world.cost(), "30", "3600.00", "120.0000")
    assert world.level(world.w1) == D("30")
    assert gap >= 0.45  # the second thread waited for the first one's commit
    assert StockMove.objects.filter(tenant=tenant).count() == 3
    _assert_reconciled(tenant, "two concurrent receipts 10@120 + 10@140 after 10@100")


# ------------------------------------------- inventory-account overrides


def _leaf_account(tenant, code, name, system_key):
    """A sibling of the given system account (same parent/type), so the
    system account itself stays a postable leaf."""
    template = Account.objects.get(tenant=tenant, system_key=system_key)
    return Account.objects.create(
        tenant=tenant, parent=template.parent, code=code, name=name, type=template.type,
        normal_balance=template.normal_balance, allow_manual_posting=False,
    )


@pytest.mark.django_db
def test_reconciliation_holds_across_an_inventory_account_override(world):
    """One company, one item: into W1 (no override) and into W3, whose
    warehouse carries its own inventory account. The system INVENTORY
    account alone no longer equals Σ ItemCost — the sum of every inventory
    account does."""
    showroom = _leaf_account(world.tenant, "1410", "مخزون مستودع المعرض", "INVENTORY")
    w3 = Warehouse.objects.create(
        tenant=world.tenant, legal_entity=world.branch1, code="W3", name="مستودع المعرض",
        inventory_account_override=showroom,
    )
    world.receipt("10", "100", date(2026, 6, 1))
    world.receipt("5", "130", date(2026, 6, 1), warehouse=w3)
    world.issue("2", date(2026, 6, 2), warehouse=w3)

    _assert_cost(world.cost(), "13", "1430.00", "110.0000")  # 1650/15 = 110; issue 2 = 220.00
    assert _balance(world.tenant, account=showroom) == D("430.00")  # 650 in, 220 out
    assert _balance(world.tenant, "INVENTORY") == D("1000.00")
    # The narrow form is false here by design — this is what the rewritten helper fixes.
    assert _balance(world.tenant, "INVENTORY") != world.cost().total_value
    _assert_reconciled(world.tenant, "W1 no override + W3 with inventory-account override")


@pytest.mark.django_db
def test_inventory_account_is_location_first_and_cogs_is_product_first(world):
    """INVENTORY: warehouse beats item. COGS: item beats warehouse."""
    item_inventory = _leaf_account(world.tenant, "1420", "مخزون الصنف", "INVENTORY")
    wh_inventory = _leaf_account(world.tenant, "1430", "مخزون المستودع", "INVENTORY")
    item_cogs = _leaf_account(world.tenant, "5051", "تكلفة خط المنتج", "COGS")
    wh_cogs = _leaf_account(world.tenant, "5052", "تكلفة المستودع", "COGS")
    item = ProductFactory(
        tenant=world.tenant, name="صنف بتجاوزات", item_type=Product.ItemType.STOCK,
        inventory_account_override=item_inventory, cogs_account_override=item_cogs,
    )
    w3 = Warehouse.objects.create(
        tenant=world.tenant, legal_entity=world.branch1, code="W3", name="مستودع بتجاوزات",
        inventory_account_override=wh_inventory, cogs_account_override=wh_cogs,
    )
    world.doc(StockDocument.Kind.RECEIPT, [{"item": item, "qty": "4", "unit_cost": "50"}], date(2026, 6, 1), warehouse=w3)
    world.doc(StockDocument.Kind.ISSUE, [{"item": item, "qty": "1"}], date(2026, 6, 2), warehouse=w3)

    assert _balance(world.tenant, account=wh_inventory) == D("150.00")
    assert _balance(world.tenant, account=item_inventory) == D("0")
    assert _balance(world.tenant, account=item_cogs) == D("50.00")
    assert _balance(world.tenant, account=wh_cogs) == D("0")
    _assert_reconciled(world.tenant, "inventory location-first, COGS product-first")


@pytest.mark.django_db
def test_goods_in_transit_nets_to_zero_across_the_company_but_not_per_branch(world):
    """Company level: after a confirmed branch-to-branch transfer,
    GOODS_IN_TRANSIT is zero. Branch level it is NOT — the transfer posts
    on the source branch, the receipt on the destination branch. Known and
    accepted (owner decision 2026-10-13): the fix is an inter-branch current
    account, deferred to sprint 12 with the inter-company entries; branch-
    level statements are not a deliverable yet. This test pins today's
    behaviour so that change is a visible, deliberate edit."""
    world.receipt("10", "100", date(2026, 6, 1))
    transfer = world.doc(
        StockDocument.Kind.TRANSFER, [{"qty": "4"}], date(2026, 6, 2), warehouse=world.w1, to_warehouse=world.w2,
    )
    confirm_transfer_receipt(transfer, world.user, date=date(2026, 6, 3))

    company_entities = LegalEntity.objects.filter(tenant=world.tenant)
    company_git = sum((_balance(world.tenant, "GOODS_IN_TRANSIT", legal_entity=e) for e in company_entities), D("0"))
    assert company_git == D("0")
    assert _balance(world.tenant, "GOODS_IN_TRANSIT", legal_entity=world.branch1) == D("400.00")
    assert _balance(world.tenant, "GOODS_IN_TRANSIT", legal_entity=world.branch2) == D("-400.00")
    _assert_reconciled(world.tenant, "confirmed transfer — GIT zero company-wide")
