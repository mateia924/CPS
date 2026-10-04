"""Sprint 7.1 (docs/prompts/sprint-7.md, block 7.1): Item extension
(D7), ItemCategory tree (D7/D18), units of measure + per-item
conversion factor (D8), multi-barcode (D9). The four tests this
block's own spec names explicitly, plus the tree cycle-check every
other self-referential model in this project already gets.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.accounting.models import TaxCode
from apps.inventory.models import ItemCategory, ItemUoM, UnitOfMeasure
from apps.inventory.services import convert_qty_to_base
from apps.organization.models import LegalEntity
from apps.sales.models import Product
from apps.sales.services import create_invoice

from .factories import PartyFactory, ProductFactory

# ---------------------------------------------------------------------
# D8: carton = 12 pieces, converted server-side
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_carton_of_12_converts_to_base_qty_server_side(tenant_a):
    piece = UnitOfMeasure.objects.create(tenant=tenant_a, code="PC", name_ar="قطعة")
    carton = UnitOfMeasure.objects.create(tenant=tenant_a, code="CTN", name_ar="كرتونة")
    item = ProductFactory(tenant=tenant_a, item_type=Product.ItemType.STOCK, base_uom=piece)
    ItemUoM.objects.create(tenant=tenant_a, item=item, uom=carton, factor_to_base=Decimal("12"))

    assert convert_qty_to_base(item, carton, Decimal("2")) == Decimal("24")
    # The base unit itself never needs an ItemUoM row — factor is 1.
    assert convert_qty_to_base(item, piece, Decimal("5")) == Decimal("5")


@pytest.mark.django_db
def test_an_unconfigured_unit_for_this_item_is_a_real_error_not_a_silent_1to1(tenant_a):
    piece = UnitOfMeasure.objects.create(tenant=tenant_a, code="PC", name_ar="قطعة")
    unrelated_uom = UnitOfMeasure.objects.create(tenant=tenant_a, code="BOX", name_ar="صندوق")
    item = ProductFactory(tenant=tenant_a, item_type=Product.ItemType.STOCK, base_uom=piece)

    with pytest.raises(ValidationError):
        convert_qty_to_base(item, unrelated_uom, Decimal("1"))


# ---------------------------------------------------------------------
# D9: a duplicate barcode -> 400 named by field
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_duplicate_barcode_is_rejected_with_400_naming_the_field(tenant_a, client_a):
    item1 = ProductFactory(tenant=tenant_a)
    item2 = ProductFactory(tenant=tenant_a)
    resp1 = client_a.post("/api/inventory/item-barcodes/", {"item": str(item1.id), "barcode": "6291041500213"})
    assert resp1.status_code == 201, resp1.data

    resp2 = client_a.post("/api/inventory/item-barcodes/", {"item": str(item2.id), "barcode": "6291041500213"})
    assert resp2.status_code == 400
    assert "barcode" in resp2.data


# ---------------------------------------------------------------------
# D7: a service item never accepts tracking
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_a_service_item_cannot_have_tracking(tenant_a, client_a):
    resp = client_a.post(
        "/api/products/",
        {"sku": "SVC-1", "name": "خدمة استشارية", "unit_price": "100.00", "item_type": "service", "tracking": "serial"},
    )
    assert resp.status_code == 400
    assert "tracking" in resp.data


@pytest.mark.django_db
def test_a_service_item_with_tracking_none_is_fine(tenant_a, client_a):
    """"" and NONE both mean "not tracked" — only SERIAL/BATCH are
    rejected for a service item (the exact distinction the first
    attempt at this check, tonight, got wrong before being caught)."""
    resp = client_a.post(
        "/api/products/",
        {"sku": "SVC-2", "name": "خدمة أخرى", "unit_price": "50.00", "item_type": "service", "tracking": "none"},
    )
    assert resp.status_code == 201, resp.data


# ---------------------------------------------------------------------
# D7: changing the base unit of an item with real movements -> 400
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_changing_base_uom_of_an_item_with_movements_is_rejected(tenant_a, client_a, user_a):
    # tenant_a already seeds the fiscal year/tax codes/legal entities —
    # re-seeding any of them here would collide (e.g. a second 2026
    # fiscal year overlapping the one the fixture already created).
    entity = LegalEntity.objects.get(tenant=tenant_a, code="MAIN-01")
    party = PartyFactory(tenant=tenant_a)
    piece = UnitOfMeasure.objects.create(tenant=tenant_a, code="PC", name_ar="قطعة")
    kg = UnitOfMeasure.objects.create(tenant=tenant_a, code="KG", name_ar="كيلوجرام")
    item = ProductFactory(tenant=tenant_a, item_type=Product.ItemType.STOCK, base_uom=piece)

    tax_code_z = TaxCode.objects.get(tenant=tenant_a, code="Z")
    create_invoice(
        tenant=tenant_a, party=party, legal_entity=entity, issue_date=date(2026, 1, 1),
        line_inputs=[{"product": item, "quantity": Decimal("1"), "cost_center": None, "tax_code": tax_code_z}],
        currency="SAR", exchange_rate=Decimal("1"),
    )

    resp = client_a.patch(f"/api/products/{item.id}/", {"base_uom": str(kg.id)})
    assert resp.status_code == 400
    assert "base_uom" in resp.data


@pytest.mark.django_db
def test_changing_base_uom_of_an_item_with_no_movements_is_allowed(tenant_a, client_a):
    piece = UnitOfMeasure.objects.create(tenant=tenant_a, code="PC", name_ar="قطعة")
    kg = UnitOfMeasure.objects.create(tenant=tenant_a, code="KG", name_ar="كيلوجرام")
    item = ProductFactory(tenant=tenant_a, item_type=Product.ItemType.STOCK, base_uom=piece)

    resp = client_a.patch(f"/api/products/{item.id}/", {"base_uom": str(kg.id)})
    assert resp.status_code == 200, resp.data


# ---------------------------------------------------------------------
# ItemCategory tree (same self-FK pattern as Account/CostCenter —
# same cycle-check rule-11 precedent this project already applies)
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_item_category_cannot_be_its_own_parent(tenant_a, client_a):
    cat = ItemCategory.objects.create(tenant=tenant_a, code="C1", name="فئة")
    resp = client_a.patch(f"/api/inventory/item-categories/{cat.id}/", {"parent": str(cat.id)})
    assert resp.status_code == 400
    assert "parent" in resp.data


@pytest.mark.django_db
def test_item_category_cycle_is_rejected(tenant_a, client_a):
    root = ItemCategory.objects.create(tenant=tenant_a, code="ROOT", name="جذر")
    child = ItemCategory.objects.create(tenant=tenant_a, code="CHILD", name="فرع", parent=root)

    resp = client_a.patch(f"/api/inventory/item-categories/{root.id}/", {"parent": str(child.id)})
    assert resp.status_code == 400
    assert "parent" in resp.data


# ---------------------------------------------------------------------
# CSV import (7.1 block spec, item 3)
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_csv_import_creates_items_and_reports_errors_per_row(tenant_a, client_a):
    from io import BytesIO

    ItemCategory.objects.create(tenant=tenant_a, code="CAT1", name="فئة أولى")
    existing = ProductFactory(tenant=tenant_a, sku="DUP-1")

    csv_content = (
        "كود,اسم,نوع,فئة,وحدة,باركود,حد إعادة الطلب,تكلفة افتراضية\n"
        "NEW-1,صنف جديد,مخزني,CAT1,,,10,5.00\n"
        f"{existing.sku},مكرر,خدمي,,,,,\n"
        "NEW-2,صنف بلا فئة,خدمي,,,,, \n"
        "NEW-3,فئة مفقودة,مخزني,NOPE,,,,\n"
    ).encode("utf-8")
    upload = BytesIO(csv_content)
    upload.name = "items.csv"

    resp = client_a.post("/api/products/import_csv/", {"file": upload}, format="multipart")
    assert resp.status_code == 200, resp.data
    assert resp.data["created"] == 2  # NEW-1 and NEW-2
    assert len(resp.data["errors"]) == 2  # the duplicate sku, the missing category
    rows_with_errors = {e["row"] for e in resp.data["errors"]}
    assert rows_with_errors == {2, 4}

    created = Product.objects.get(tenant=tenant_a, sku="NEW-1")
    assert created.category.code == "CAT1"
    assert created.item_type == Product.ItemType.STOCK
    assert created.reorder_level == Decimal("10")


@pytest.mark.django_db
def test_csv_import_requires_a_file(tenant_a, client_a):
    resp = client_a.post("/api/products/import_csv/", {}, format="multipart")
    assert resp.status_code == 400
