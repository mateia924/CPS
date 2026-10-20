"""Sprint 8.1 (docs/prompts/sprint-8.md, block 8.1): supplier bills with
service, expense and asset lines — D4 for those line types, R-8.6
(non-deductible VAT capitalized, reverse charge both sides), R-8.7 (the
asset record from a bill line, as built: ACTIVE, no in-service date), the
workflow and its guards, and the expenses list.

The spec's fixed numbers: rent 10,000 + 15% deductible; telecoms 1,000 +
15% non-deductible -> 1,150; foreign service RC 5,000 nets to zero; an
asset line of 20,000; a duplicate supplier invoice number -> 400 naming
the field; a mandatory-attachment rule at 5,000 -> 400 with its text.
Rule 34's restricted-role test is in test_rls.py.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounting.models import Account, JournalEntry, TaxCode
from apps.accounting.services import get_system_account
from apps.approvals.models import ApprovalRule
from apps.assets.models import Asset
from apps.attachments.models import AttachmentRule
from apps.organization.models import LegalEntity
from apps.parties.models import Party, PartyRole
from apps.purchasing.models import SupplierBill

from .factories import LegalEntityFactory, UserFactory

BILL_DATE = "2026-03-10"


@pytest.fixture
def purchasing(tenant_a):
    tenant_a.features.purchasing = True
    tenant_a.features.save(update_fields=["purchasing"])
    return tenant_a


def _supplier(tenant, name="مؤجر المكتب", **role_fields):
    party = Party.objects.create(tenant=tenant, code=f"S-{name[:6]}-{Party.objects.count()}", name=name)
    PartyRole.objects.create(party=party, role=PartyRole.Role.SUPPLIER, **role_fields)
    return party


def _expense_account(tenant):
    account = (
        Account.objects.filter(
            tenant=tenant, type=Account.Type.EXPENSE, is_active=True, allow_posting=True,
            allow_manual_posting=True, system_key="",
        )
        .order_by("code")
    )
    for candidate in account:
        if candidate.can_post:
            return candidate
    raise AssertionError("no postable expense account in the seeded chart")


def _tax(tenant, code):
    return TaxCode.objects.get(tenant=tenant, code=code)


def _branch(tenant):
    return LegalEntity.objects.filter(tenant=tenant).exclude(entity_type=LegalEntity.Type.HOLDING).first()


def _line(line_type, unit_price, tax_code, **extra):
    return {"line_type": line_type, "qty": "1", "unit_price": str(unit_price), "tax_code": str(tax_code.id), **extra}


def _create(client, tenant, supplier, lines, bill_number="INV-1001", **header):
    response = client.post(
        "/api/purchasing/bills/",
        {
            "legal_entity": str(_branch(tenant).id), "supplier": str(supplier.id), "bill_number": bill_number,
            "date": BILL_DATE, "lines": lines, **header,
        },
        format="json",
    )
    return response


def _post(client, bill_id):
    submitted = client.post(f"/api/purchasing/bills/{bill_id}/submit/")
    assert submitted.status_code == 200, submitted.data  # no ApprovalRule in the fixture: auto-approved
    posted = client.post(f"/api/purchasing/bills/{bill_id}/post/")
    assert posted.status_code == 200, posted.data
    return posted.data


def _entry_lines(bill_id):
    """{account label: (debit, credit)} — label is the system_key, or
    'supplier' for the supplier's sub-ledger account, or the account code."""
    bill = SupplierBill.objects.get(id=bill_id)
    entry = bill.journal_entry
    assert entry is not None and entry.status == JournalEntry.Status.POSTED
    assert entry.produced_by == JournalEntry.ProducedBy.SUPPLIER_BILL
    out = {}
    for line in entry.lines.select_related("account"):
        if line.account.party_id == bill.supplier_id:
            label = "supplier"
        else:
            label = line.account.system_key or line.account.code
        debit, credit = out.get(label, (Decimal("0"), Decimal("0")))
        out[label] = (debit + line.debit, credit + line.credit)
    total_debit = sum(d for d, _c in out.values())
    total_credit = sum(c for _d, c in out.values())
    assert total_debit == total_credit
    return out


# --- the spec's fixed numbers ------------------------------------------------


@pytest.mark.django_db
def test_rent_10000_with_15_percent_deductible_vat(purchasing, client_a):
    rent = _expense_account(purchasing)
    supplier = _supplier(purchasing)
    created = _create(client_a, purchasing, supplier, [_line("expense", "10000.00", _tax(purchasing, "S"), account=str(rent.id))])
    assert created.status_code == 201, created.data
    assert (created.data["subtotal"], created.data["deductible_tax"], created.data["total"]) == (
        "10000.00", "1500.00", "11500.00",
    )
    _post(client_a, created.data["id"])
    assert _entry_lines(created.data["id"]) == {
        rent.code: (Decimal("10000.00"), Decimal("0")),
        "VAT_INPUT": (Decimal("1500.00"), Decimal("0")),
        "supplier": (Decimal("0"), Decimal("11500.00")),
    }


@pytest.mark.django_db
@pytest.mark.parametrize("how", ["switch_off", "non_deductible_code"])
def test_telecoms_1000_with_non_deductible_vat_is_capitalized_to_1150(purchasing, client_a, how):
    telecoms = _expense_account(purchasing)
    supplier = _supplier(purchasing, "شركة الاتصالات")
    if how == "switch_off":
        line = _line("expense", "1000.00", _tax(purchasing, "S"), account=str(telecoms.id), vat_deductible=False)
    else:
        line = _line("expense", "1000.00", _tax(purchasing, "SN"), account=str(telecoms.id))
    created = _create(client_a, purchasing, supplier, [line])
    assert created.status_code == 201, created.data
    assert (created.data["capitalized_tax"], created.data["deductible_tax"], created.data["total"]) == (
        "150.00", "0.00", "1150.00",
    )
    _post(client_a, created.data["id"])
    assert _entry_lines(created.data["id"]) == {
        telecoms.code: (Decimal("1150.00"), Decimal("0")),
        "supplier": (Decimal("0"), Decimal("1150.00")),
    }


@pytest.mark.django_db
def test_foreign_service_reverse_charge_5000_nets_to_zero(purchasing, client_a):
    consulting = _expense_account(purchasing)
    supplier = _supplier(purchasing, "Foreign Consulting Ltd", is_resident=False)
    created = _create(
        client_a, purchasing, supplier, [_line("service", "5000.00", _tax(purchasing, "RC"), account=str(consulting.id))]
    )
    assert created.status_code == 201, created.data
    assert (created.data["reverse_charge_tax"], created.data["total"]) == ("750.00", "5000.00")
    _post(client_a, created.data["id"])
    assert _entry_lines(created.data["id"]) == {
        consulting.code: (Decimal("5000.00"), Decimal("0")),
        "VAT_INPUT": (Decimal("750.00"), Decimal("0")),
        "VAT_OUTPUT": (Decimal("0"), Decimal("750.00")),
        "supplier": (Decimal("0"), Decimal("5000.00")),
    }


@pytest.mark.django_db
def test_asset_line_20000_creates_an_active_asset_not_in_service(purchasing, client_a):
    supplier = _supplier(purchasing, "مورد معدات")
    created = _create(
        client_a, purchasing, supplier,
        [_line("asset", "20000.00", _tax(purchasing, "O"), asset_name="رافعة شوكية", asset_category="equipment")],
    )
    assert created.status_code == 201, created.data
    bill = _post(client_a, created.data["id"])
    asset = Asset.objects.get(source_bill_line__bill_id=created.data["id"])
    assert asset.status == Asset.Status.ACTIVE
    assert asset.in_service_date is None
    assert asset.purchase_cost == Decimal("20000.00")
    assert asset.purchase_reference == bill["number"]
    assert asset.purchase_date == date(2026, 3, 10)
    assert (asset.name, asset.category, asset.legal_entity_id) == ("رافعة شوكية", "equipment", _branch(purchasing).id)
    assert bill["lines"][0]["asset_code"] == asset.code
    assert _entry_lines(created.data["id"]) == {
        "FIXED_ASSETS": (Decimal("20000.00"), Decimal("0")),
        "supplier": (Decimal("0"), Decimal("20000.00")),
    }


@pytest.mark.django_db
def test_duplicate_supplier_invoice_number_is_a_400_naming_the_field(purchasing, client_a):
    rent = _expense_account(purchasing)
    supplier = _supplier(purchasing)
    line = [_line("expense", "100.00", _tax(purchasing, "S"), account=str(rent.id))]
    assert _create(client_a, purchasing, supplier, line, bill_number="DUP-7").status_code == 201
    again = _create(client_a, purchasing, supplier, line, bill_number="DUP-7")
    assert again.status_code == 400
    assert "bill_number" in again.data
    assert "DUP-7" in again.data["bill_number"][0]
    # Another supplier may use the same number.
    other = _supplier(purchasing, "مورد آخر")
    assert _create(client_a, purchasing, other, line, bill_number="DUP-7").status_code == 201


@pytest.mark.django_db
def test_mandatory_attachment_rule_at_5000_refuses_submit_without_it(purchasing, client_a):
    AttachmentRule.objects.create(
        tenant=purchasing, doc_type=AttachmentRule.DocType.SUPPLIER_BILL,
        min_amount_base=Decimal("5000"), required_category="fatura_original", is_active=True,
    )
    rent = _expense_account(purchasing)
    created = _create(
        client_a, purchasing, _supplier(purchasing), [_line("expense", "6000.00", _tax(purchasing, "S"), account=str(rent.id))]
    )
    refused = client_a.post(f"/api/purchasing/bills/{created.data['id']}/submit/")
    assert refused.status_code == 400
    assert "المستند يتطلب مرفق «فاتورة المورد الأصلية» لأنه يتجاوز" in refused.data["detail"]
    assert SupplierBill.objects.get(id=created.data["id"]).status == SupplierBill.Status.DRAFT

    upload = SimpleUploadedFile(
        "bill.pdf",
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF",
        content_type="application/pdf",
    )
    attached = client_a.post(
        "/api/attachments/",
        {"target_type": "supplier_bill", "target_id": created.data["id"], "category": "fatura_original", "file": upload},
        format="multipart",
    )
    assert attached.status_code == 201, attached.data
    assert client_a.post(f"/api/purchasing/bills/{created.data['id']}/submit/").status_code == 200


# --- workflow and guards -----------------------------------------------------


@pytest.mark.django_db
def test_posted_bill_cannot_be_edited_or_deleted(purchasing, client_a):
    rent = _expense_account(purchasing)
    created = _create(
        client_a, purchasing, _supplier(purchasing), [_line("expense", "100.00", _tax(purchasing, "S"), account=str(rent.id))]
    )
    _post(client_a, created.data["id"])
    edited = client_a.patch(f"/api/purchasing/bills/{created.data['id']}/", {"notes": "x"}, format="json")
    assert edited.status_code == 409
    assert client_a.delete(f"/api/purchasing/bills/{created.data['id']}/").status_code == 409


@pytest.mark.django_db
def test_only_an_approved_bill_posts(purchasing, client_a):
    rent = _expense_account(purchasing)
    created = _create(
        client_a, purchasing, _supplier(purchasing), [_line("expense", "100.00", _tax(purchasing, "S"), account=str(rent.id))]
    )
    refused = client_a.post(f"/api/purchasing/bills/{created.data['id']}/post/")
    assert refused.status_code == 400
    assert "المعتمدة" in refused.data["detail"]
    assert SupplierBill.objects.get(id=created.data["id"]).journal_entry is None


@pytest.mark.django_db
def test_approval_rule_holds_the_bill_and_a_second_user_approves_it(purchasing, client_a, user_a):
    from apps.access.models import Role

    owner_role = Role.objects.get(tenant=purchasing, name="Owner", is_system=True)
    ApprovalRule.objects.create(tenant=purchasing, doc_type="supplier_bill", min_amount=0, required_role=owner_role)
    rent = _expense_account(purchasing)
    created = _create(
        client_a, purchasing, _supplier(purchasing), [_line("expense", "100.00", _tax(purchasing, "S"), account=str(rent.id))]
    )
    held = client_a.post(f"/api/purchasing/bills/{created.data['id']}/submit/")
    assert held.status_code == 202
    assert held.data["status"] == "pending_approval" and held.data["number"].startswith("PINV-")

    approver = UserFactory(tenant=purchasing)
    approver.roles.add(owner_role)
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(approver)
    inbox = client.get("/api/approvals/pending/")
    assert any(row["doc_type"] == "supplier_bill" and row["id"] == created.data["id"] for row in inbox.data["results"])
    assert client.post(f"/api/purchasing/bills/{created.data['id']}/approve/").status_code == 200
    assert client.post(f"/api/purchasing/bills/{created.data['id']}/post/").status_code == 200


@pytest.mark.django_db
def test_reversal_mirrors_the_entry_and_withdraws_the_assets_it_created(purchasing, client_a):
    created = _create(
        client_a, purchasing, _supplier(purchasing),
        [_line("asset", "20000.00", _tax(purchasing, "O"), asset_name="خادم", asset_category="it")],
    )
    _post(client_a, created.data["id"])
    asset = Asset.objects.get(source_bill_line__bill_id=created.data["id"])
    reversed_ = client_a.post(f"/api/purchasing/bills/{created.data['id']}/reverse/", {"reason": "فاتورة مكررة"}, format="json")
    assert reversed_.status_code == 200, reversed_.data
    assert reversed_.data["status"] == "reversed"
    original = SupplierBill.objects.get(id=created.data["id"]).journal_entry
    mirror = JournalEntry.objects.get(reverses=original)
    assert sorted((line.debit, line.credit) for line in mirror.lines.all()) == sorted(
        (line.credit, line.debit) for line in original.lines.all()
    )
    asset.refresh_from_db()
    assert asset.deleted_at is not None


@pytest.mark.django_db
def test_reversal_is_refused_once_the_asset_has_started_depreciating(purchasing, client_a):
    created = _create(
        client_a, purchasing, _supplier(purchasing),
        [_line("asset", "12000.00", _tax(purchasing, "O"), asset_name="سيارة", asset_category="vehicle")],
    )
    _post(client_a, created.data["id"])
    asset = Asset.objects.get(source_bill_line__bill_id=created.data["id"])
    asset.in_service_date = date(2026, 3, 15)
    asset.useful_life_months = 60
    asset.save(update_fields=["in_service_date", "useful_life_months"])
    started = client_a.post(f"/api/assets/{asset.id}/start-depreciation/")
    assert started.status_code in (200, 201, 202), started.data
    refused = client_a.post(f"/api/purchasing/bills/{created.data['id']}/reverse/", {"reason": "خطأ"}, format="json")
    assert refused.status_code == 400
    assert "بدأ إهلاكه" in refused.data["detail"]
    assert SupplierBill.objects.get(id=created.data["id"]).status == SupplierBill.Status.POSTED


@pytest.mark.django_db
def test_depreciation_is_refused_for_a_bill_asset_with_no_in_service_date(purchasing, client_a):
    created = _create(
        client_a, purchasing, _supplier(purchasing),
        [_line("asset", "20000.00", _tax(purchasing, "O"), asset_name="رافعة", asset_category="equipment")],
    )
    _post(client_a, created.data["id"])
    asset = Asset.objects.get(source_bill_line__bill_id=created.data["id"])
    asset.useful_life_months = 60
    asset.save(update_fields=["useful_life_months"])
    refused = client_a.post(f"/api/assets/{asset.id}/start-depreciation/")
    assert refused.status_code == 400
    assert "لم يُحدَّد تاريخ بدء الخدمة" in str(refused.data)
    asset.refresh_from_db()
    assert asset.in_service_date is None and asset.depreciation_entry_id is None

    asset.in_service_date = date(2026, 4, 1)
    asset.save(update_fields=["in_service_date"])
    assert client_a.post(f"/api/assets/{asset.id}/start-depreciation/").status_code in (200, 201, 202)


@pytest.mark.django_db
def test_module_off_is_404_and_a_role_without_purchasing_view_is_403(tenant_a, client_a):
    assert client_a.get("/api/purchasing/bills/").status_code == 404
    tenant_a.features.purchasing = True
    tenant_a.features.save(update_fields=["purchasing"])
    from rest_framework.test import APIClient

    from apps.access.models import Role

    viewer = UserFactory(tenant=tenant_a)
    viewer.roles.add(Role.objects.get(tenant=tenant_a, name="Viewer", is_system=True))
    client = APIClient()
    client.force_authenticate(viewer)
    assert client.get("/api/purchasing/bills/").status_code == 403
    assert client.get("/api/purchasing/expenses/").status_code == 403


@pytest.mark.django_db
def test_lines_name_their_problem(purchasing, client_a):
    supplier = _supplier(purchasing)
    no_account = _create(client_a, purchasing, supplier, [_line("expense", "100.00", _tax(purchasing, "S"))])
    assert no_account.status_code == 400 and "السطر 1" in no_account.data["lines"][0]
    control = get_system_account(purchasing, "VAT_INPUT")
    on_control = _create(
        client_a, purchasing, supplier, [_line("expense", "100.00", _tax(purchasing, "S"), account=str(control.id))],
        bill_number="X-2",
    )
    assert on_control.status_code == 400 and control.code in on_control.data["lines"][0]
    no_name = _create(
        client_a, purchasing, supplier, [_line("asset", "100.00", _tax(purchasing, "O"), asset_category="it")],
        bill_number="X-3",
    )
    assert no_name.status_code == 400 and "اسم الأصل" in no_name.data["lines"][0]


@pytest.mark.django_db
def test_supplier_default_expense_account_fills_a_line_without_one(purchasing, client_a):
    rent = _expense_account(purchasing)
    supplier = _supplier(purchasing, default_expense_account=rent)
    created = _create(client_a, purchasing, supplier, [_line("expense", "100.00", _tax(purchasing, "S"))])
    assert created.status_code == 201, created.data
    assert str(created.data["lines"][0]["account"]) == str(rent.id)


# --- expenses list -----------------------------------------------------------


@pytest.mark.django_db
def test_expenses_list_holds_bill_expense_lines_only_when_posted(purchasing, client_a):
    rent = _expense_account(purchasing)
    supplier = _supplier(purchasing)
    posted = _create(
        client_a, purchasing, supplier,
        [
            _line("expense", "1000.00", _tax(purchasing, "SN"), account=str(rent.id), description="اتصالات مارس"),
            _line("service", "500.00", _tax(purchasing, "S"), account=str(rent.id), description="صيانة"),
        ],
    )
    _post(client_a, posted.data["id"])
    _create(
        client_a, purchasing, supplier, [_line("expense", "999.00", _tax(purchasing, "S"), account=str(rent.id))],
        bill_number="DRAFT-1",
    )
    listed = client_a.get("/api/purchasing/expenses/")
    assert listed.status_code == 200
    rows = listed.data["results"]
    assert [(r["source"], r["description"], r["amount"], r["account_code"]) for r in rows] == [
        ("supplier_bill", "اتصالات مارس", "1150.00", rent.code)
    ]
    assert listed.data["total_base"] == "1150.00"
    other = get_system_account(purchasing, "VAT_INPUT")
    assert client_a.get(f"/api/purchasing/expenses/?account={other.id}").data["count"] == 0


@pytest.mark.django_db
def test_expenses_list_holds_voucher_expense_lines_only_for_a_user_who_may_see_vouchers(purchasing, client_a):
    from rest_framework.test import APIClient

    from apps.access.models import Role

    from .test_attachment_rules import _fund_cash_box, _make_cash_box, _make_payment_voucher

    cash_box = _make_cash_box(client_a, purchasing)
    _fund_cash_box(client_a, purchasing, cash_box)
    voucher = _make_payment_voucher(client_a, purchasing, cash_box, "300.00")
    assert client_a.post(f"/api/vouchers/{voucher['id']}/post/").status_code == 200

    rows = client_a.get("/api/purchasing/expenses/").data["results"]
    assert [(r["source"], r["amount"], r["account_code"]) for r in rows] == [("voucher", "300.00", "5100")]

    rent = _expense_account(purchasing)
    bill = _create(
        client_a, purchasing, _supplier(purchasing),
        [_line("expense", "200.00", _tax(purchasing, "Z"), account=str(rent.id), description="بند فاتورة")],
    )
    _post(client_a, bill.data["id"])

    from apps.access.models import UserEntityAccess

    buyer = UserFactory(tenant=purchasing)
    buyer.roles.add(Role.objects.get(tenant=purchasing, name="Purchasing", is_system=True))
    # The same entity as both documents, so only the permission can hide a row.
    UserEntityAccess.objects.create(user=buyer, legal_entity=_branch(purchasing))
    client = APIClient()
    client.force_authenticate(buyer)
    seen = client.get("/api/purchasing/expenses/")
    assert seen.status_code == 200
    # purchasing.view, no vouchers.view: the bill line, never the voucher's.
    assert [r["source"] for r in seen.data["results"]] == ["supplier_bill"]


@pytest.mark.django_db
def test_a_bill_assets_purchase_cost_cannot_be_edited_from_the_asset_screen(purchasing, client_a):
    created = _create(
        client_a, purchasing, _supplier(purchasing),
        [_line("asset", "20000.00", _tax(purchasing, "O"), asset_name="رافعة", asset_category="equipment")],
    )
    _post(client_a, created.data["id"])
    asset = Asset.objects.get(source_bill_line__bill_id=created.data["id"])
    refused = client_a.patch(f"/api/assets/{asset.id}/", {"purchase_cost": "25000.00"}, format="json")
    assert refused.status_code == 400
    assert "purchase_cost" in refused.data and "فاتورة مورد" in refused.data["purchase_cost"][0]
    asset.refresh_from_db()
    assert asset.purchase_cost == Decimal("20000.00")
    # Everything that is not the bill's money stays editable.
    renamed = client_a.patch(f"/api/assets/{asset.id}/", {"useful_life_months": 60, "name": "رافعة 3 طن"}, format="json")
    assert renamed.status_code == 200, renamed.data
    assert renamed.data["source_bill"]["number"] == SupplierBill.objects.get(id=created.data["id"]).number


@pytest.mark.django_db
def test_an_asset_entered_by_hand_still_starts_from_its_purchase_date(purchasing, client_a):
    """The no-in-service-date refusal is for bill assets only: an asset
    entered by hand keeps 6.5's fallback to its purchase date."""
    branch = _branch(purchasing)
    asset = Asset.objects.create(
        tenant=purchasing, legal_entity=branch, code="MAN-1", name="مكتب", category="furniture",
        purchase_date=date(2026, 2, 1), purchase_cost=Decimal("3000.00"), useful_life_months=36,
    )
    assert client_a.post(f"/api/assets/{asset.id}/start-depreciation/").status_code in (200, 201, 202)
    asset.refresh_from_db()
    assert asset.in_service_date == date(2026, 2, 1)


@pytest.mark.django_db
def test_header_guards_name_their_field(purchasing, client_a):
    rent = _expense_account(purchasing)
    line = [_line("expense", "100.00", _tax(purchasing, "S"), account=str(rent.id))]
    customer_only = Party.objects.create(tenant=purchasing, code="C-ONLY", name="عميل فقط")
    PartyRole.objects.create(party=customer_only, role=PartyRole.Role.CUSTOMER)
    not_supplier = _create(client_a, purchasing, customer_only, line, bill_number="H-1")
    assert not_supplier.status_code == 400 and "ليس موردًا" in str(not_supplier.data["supplier"])

    supplier = _supplier(purchasing)
    holding = LegalEntityFactory(tenant=purchasing, entity_type=LegalEntity.Type.HOLDING)
    on_holding = client_a.post(
        "/api/purchasing/bills/",
        {"legal_entity": str(holding.id), "supplier": str(supplier.id), "bill_number": "H-2", "date": BILL_DATE,
         "lines": line},
        format="json",
    )
    assert on_holding.status_code == 400 and "القابضة" in str(on_holding.data["legal_entity"]), on_holding.data

    early_due = _create(client_a, purchasing, supplier, line, bill_number="H-3", due_date="2026-03-01")
    assert early_due.status_code == 400 and "قبل تاريخ الفاتورة" in str(early_due.data["due_date"])
