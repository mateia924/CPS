"""Sprint 6.7 (3.17 rule 4, sprint-6.md decision 15): AttachmentRule —
"سند صرف ≥ 5,000 يتطلب فاتورة أصلية"، checked once, generically, inside
apps.approvals.services.submit_for_approval (the one choke point every
document type's submit/issue/post path already goes through).
"""

from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounting.models import Account, TaxCode
from apps.attachments.models import AttachmentRule
from apps.organization.models import LegalEntity


def _branch(tenant):
    return LegalEntity.objects.get(tenant=tenant, entity_type=LegalEntity.Type.BRANCH)


def _make_cash_box(client, tenant):
    response = client.post(
        "/api/cash-boxes/", {"legal_entity": str(_branch(tenant).id), "name": "Cash box", "currency": "SAR"}, format="json"
    )
    assert response.status_code == 201, response.data
    return response.data


def _fund_cash_box(client, tenant, cash_box, amount="10000.00"):
    revenue = Account.objects.filter(tenant=tenant, code="4100").first()
    tax_code = TaxCode.objects.get(tenant=tenant, code="Z")
    response = client.post(
        "/api/vouchers/",
        {
            "voucher_type": "receipt", "legal_entity": str(_branch(tenant).id), "date": "2026-09-01",
            "treasury_kind": "cash_box", "treasury_id": cash_box["id"], "payee_name": "Funding",
            "lines": [
                {"line_type": "account", "account": str(revenue.id), "tax_code": str(tax_code.id), "amount_fc": amount}
            ],
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    posted = client.post(f"/api/vouchers/{response.data['id']}/post/")
    assert posted.status_code == 200, posted.data


def _make_payment_voucher(client, tenant, cash_box, amount):
    expense = Account.objects.filter(tenant=tenant, code="5100").first()
    tax_code = TaxCode.objects.get(tenant=tenant, code="Z")
    response = client.post(
        "/api/vouchers/",
        {
            "voucher_type": "payment", "legal_entity": str(_branch(tenant).id), "date": "2026-09-05",
            "treasury_kind": "cash_box", "treasury_id": cash_box["id"], "payee_name": "Supplier",
            "lines": [
                {"line_type": "account", "account": str(expense.id), "tax_code": str(tax_code.id), "amount_fc": amount}
            ],
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    return response.data


def _attach_original_invoice(client, voucher_id):
    upload = SimpleUploadedFile(
        "invoice.pdf",
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF",
        content_type="application/pdf",
    )
    response = client.post(
        "/api/attachments/",
        {"target_type": "voucher", "target_id": voucher_id, "category": "fatura_original", "file": upload},
        format="multipart",
    )
    assert response.status_code == 201, response.data


@pytest.mark.django_db
def test_payment_voucher_over_threshold_without_attachment_rejected(tenant_a, client_a):
    AttachmentRule.objects.create(
        tenant=tenant_a, doc_type=AttachmentRule.DocType.VOUCHER_PAYMENT,
        min_amount_base=Decimal("5000"), required_category="fatura_original", is_active=True,
    )
    cash_box = _make_cash_box(client_a, tenant_a)
    _fund_cash_box(client_a, tenant_a, cash_box)

    voucher = _make_payment_voucher(client_a, tenant_a, cash_box, "6000.00")
    response = client_a.post(f"/api/vouchers/{voucher['id']}/post/")
    assert response.status_code == 400, response.data
    assert "فاتورة المورد الأصلية" in str(response.data)


@pytest.mark.django_db
def test_payment_voucher_over_threshold_with_attachment_passes(tenant_a, client_a):
    AttachmentRule.objects.create(
        tenant=tenant_a, doc_type=AttachmentRule.DocType.VOUCHER_PAYMENT,
        min_amount_base=Decimal("5000"), required_category="fatura_original", is_active=True,
    )
    cash_box = _make_cash_box(client_a, tenant_a)
    _fund_cash_box(client_a, tenant_a, cash_box)

    voucher = _make_payment_voucher(client_a, tenant_a, cash_box, "6000.00")
    _attach_original_invoice(client_a, voucher["id"])
    response = client_a.post(f"/api/vouchers/{voucher['id']}/post/")
    assert response.status_code == 200, response.data


@pytest.mark.django_db
def test_payment_voucher_under_threshold_without_attachment_passes(tenant_a, client_a):
    AttachmentRule.objects.create(
        tenant=tenant_a, doc_type=AttachmentRule.DocType.VOUCHER_PAYMENT,
        min_amount_base=Decimal("5000"), required_category="fatura_original", is_active=True,
    )
    cash_box = _make_cash_box(client_a, tenant_a)
    _fund_cash_box(client_a, tenant_a, cash_box)

    voucher = _make_payment_voucher(client_a, tenant_a, cash_box, "4000.00")
    response = client_a.post(f"/api/vouchers/{voucher['id']}/post/")
    assert response.status_code == 200, response.data


@pytest.mark.django_db
def test_tenant_isolation(tenant_a, tenant_b, client_a, client_b):
    AttachmentRule.objects.create(
        tenant=tenant_a, doc_type=AttachmentRule.DocType.VOUCHER_PAYMENT,
        min_amount_base=Decimal("5000"), required_category="fatura_original", is_active=True,
    )
    response = client_b.get("/api/attachment-rules/")
    assert response.status_code == 200
    assert response.data["count"] == 0
