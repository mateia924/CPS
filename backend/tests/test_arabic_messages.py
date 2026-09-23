"""Sprint 6.0, item 3/5/§11 decision (2026-09-23): every newly-posted
journal entry must carry an Arabic memo (invoice issuance, invoice
void, manual-entry reversal, voucher posting) — even though the 8
pre-existing English-prefixed memos on the dev tenant are left
untouched by design (protect_posted_journal_entry() forbids editing a
POSTED entry's memo; see README "ديون تقنية" and
docs/SYSTEM_ANALYSIS.md §11). This file only proves the *forward*
guarantee: nothing here ever mutates an already-posted entry.
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.access.services import seed_default_roles
from apps.accounting.models import Account, JournalEntry, TaxCode
from apps.accounting.services import (
    create_manual_journal_entry,
    post_journal_entry,
    reverse_journal_entry,
    submit_journal_entry_for_approval,
)

from .factories import LegalEntityFactory, PartyFactory, ProductFactory, UserFactory


def _branch(tenant):
    from apps.organization.models import LegalEntity

    return LegalEntity.objects.get(tenant=tenant, entity_type=LegalEntity.Type.BRANCH)


@pytest.mark.django_db
def test_new_invoice_issuance_entry_has_arabic_memo(tenant_a, client_a):
    customer = PartyFactory(tenant=tenant_a)
    product = ProductFactory(tenant=tenant_a)
    tax_code = TaxCode.objects.get(tenant=tenant_a, code="Z")
    invoice = client_a.post(
        "/api/invoices/",
        {
            "customer": str(customer.id),
            "lines": [{"product": str(product.id), "quantity": "1", "tax_code": str(tax_code.id)}],
        },
        format="json",
    ).data
    issued = client_a.post(f"/api/invoices/{invoice['id']}/issue/")
    assert issued.status_code == 200, issued.data

    entry = JournalEntry.objects.get(id=issued.data["journal_entry_id"])
    assert entry.memo.startswith("فاتورة ")
    assert issued.data["number"] in entry.memo


@pytest.mark.django_db
def test_void_invoice_reversal_entry_has_arabic_memo(tenant_a, client_a):
    customer = PartyFactory(tenant=tenant_a)
    product = ProductFactory(tenant=tenant_a)
    tax_code = TaxCode.objects.get(tenant=tenant_a, code="Z")
    invoice = client_a.post(
        "/api/invoices/",
        {
            "customer": str(customer.id),
            "lines": [{"product": str(product.id), "quantity": "1", "tax_code": str(tax_code.id)}],
        },
        format="json",
    ).data
    client_a.post(f"/api/invoices/{invoice['id']}/issue/")

    voided = client_a.post(f"/api/invoices/{invoice['id']}/void/")
    assert voided.status_code == 200, voided.data

    reversal = JournalEntry.objects.get(source_type="invoice_void", source_id=invoice["id"])
    assert reversal.memo.startswith("إلغاء فاتورة ")


@pytest.mark.django_db
def test_manual_entry_reversal_has_arabic_memo(tenant_a):
    roles = seed_default_roles(tenant_a)
    entity = LegalEntityFactory(tenant=tenant_a)
    creator = UserFactory(tenant=tenant_a, email="creator@arabic-memo.test")
    creator.roles.add(roles["Owner"])
    cash = Account.objects.get(tenant=tenant_a, system_key="CASH")
    sales = Account.objects.get(tenant=tenant_a, system_key="SALES")

    entry = create_manual_journal_entry(
        tenant=tenant_a, user=creator, legal_entity=entity, date=date(2026, 1, 1),
        line_specs=[
            {"account": cash, "debit_fc": Decimal("50.00"), "credit_fc": Decimal("0")},
            {"account": sales, "debit_fc": Decimal("0"), "credit_fc": Decimal("50.00")},
        ],
        currency="SAR", exchange_rate=Decimal("1"),
    )
    # Single-active-user tenant (only "creator" holds a role here) — the
    # 3.15.9 self-approval exemption auto-approves on submit, same as
    # tests/test_journal_engine.py's non-segregated-duty cases.
    submit_journal_entry_for_approval(entry, creator)
    post_journal_entry(entry, creator)

    reversal = reverse_journal_entry(entry, creator, "اختبار")
    assert reversal.memo.startswith("عكس قيد ")
    assert entry.number in reversal.memo


@pytest.mark.django_db
def test_posted_voucher_entry_has_arabic_memo(tenant_a, client_a):
    bank = client_a.post(
        "/api/banks/",
        {"legal_entity": str(_branch(tenant_a).id), "name": "Bank", "currency": "SAR"},
        format="json",
    ).data
    revenue = Account.objects.filter(tenant=tenant_a, code="4100").first()
    tax_code = TaxCode.objects.get(tenant=tenant_a, code="Z")

    voucher = client_a.post(
        "/api/vouchers/",
        {
            "voucher_type": "receipt",
            "legal_entity": str(_branch(tenant_a).id),
            "date": "2026-09-23",
            "treasury_kind": "bank",
            "treasury_id": bank["id"],
            "payee_name": "Test",
            "lines": [
                {"line_type": "account", "account": str(revenue.id), "tax_code": str(tax_code.id), "amount_fc": "100.00"}
            ],
        },
        format="json",
    ).data
    posted = client_a.post(f"/api/vouchers/{voucher['id']}/post/")
    assert posted.status_code == 200, posted.data

    entry = JournalEntry.objects.get(id=posted.data["journal_entry_id"])
    # get_voucher_type_display() renders through the Arabic gettext
    # catalog (LANGUAGE_CODE="ar" is this project's default) — sprint
    # 6.0 changed the VoucherType msgids to "Receipt Voucher"/etc to
    # avoid colliding with Attachment.Category's own "Receipt" msgid.
    assert entry.memo.startswith("سند ")
