"""Sprint 6.0, item 3/5/§11 decision (2026-09-23): every newly-posted
journal entry must carry an Arabic memo (invoice issuance, invoice
void, manual-entry reversal, voucher posting) — even though the 8
pre-existing English-prefixed memos on the dev tenant are left
untouched by design (protect_posted_journal_entry() forbids editing a
POSTED entry's memo; see README "ديون تقنية" and
docs/SYSTEM_ANALYSIS.md §11). This file only proves the *forward*
guarantee: nothing here ever mutates an already-posted entry.
"""

import re
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


# ---------------------------------------------------------------------
# Sprint 6.0.1-B item 7 (completes 6.0-5): a structural sweep — not a
# handful of scenarios chosen ahead of time, but every financial
# ViewSet's create action (empty payload → 400), a permission-less user
# against one of them (→ 403), and a known state-conflict (→ 409) — all
# asserted to carry only Arabic message text. No English message may
# slip through a ViewSet nobody wrote a scenario test for.
# ---------------------------------------------------------------------

_ARABIC_RE = re.compile(r"[؀-ۿ]")
# A value that is ALL of: ascii letters/digits/basic punctuation, no
# Arabic — i.e. looks like an untranslated English sentence or an
# internal code slipping into a user-facing message.
_LOOKS_ENGLISH_RE = re.compile(r"^[A-Za-z0-9 .,'_()-]+$")

# Explicit, reviewed exemptions only (3.15's own rule: "استثناءات
# موثَّقة بقائمة صريحة فقط") — values that are correctly ASCII-only
# because they're not prose at all (a bare field name echoed back, a
# currency code, a UUID/pk fragment DRF itself generates).
_EXEMPT_VALUES = {
    "SAR",  # default currency code echoed in some validators, not prose
}


def _walk_message_strings(value):
    """Yield every leaf string in a DRF error response body — dict KEYS
    (field names) are deliberately not checked, only the message text
    each key maps to (the rule's own "نصوص detail/الحقول لا أسماء
    الحقول")."""
    if isinstance(value, dict):
        for v in value.values():
            yield from _walk_message_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk_message_strings(v)
    elif isinstance(value, str):
        yield value


def _assert_all_arabic(body, path):
    for text in _walk_message_strings(body):
        if text in _EXEMPT_VALUES:
            continue
        if _ARABIC_RE.search(text):
            continue
        if not _LOOKS_ENGLISH_RE.match(text):
            # Contains non-ASCII, non-Arabic characters (e.g. a UUID) —
            # not prose, nothing to translate.
            continue
        raise AssertionError(f"{path}: non-Arabic message text found: {text!r}")


# Every financial ViewSet's create route — POST with an empty payload
# must 400 with field-required messages, all in Arabic (DRF/Django's
# own bundled ar translations cover "This field is required." etc.).
_EMPTY_PAYLOAD_400_PATHS = [
    "/api/invoices/",
    "/api/customers/",
    "/api/products/",
    "/api/accounts/",
    "/api/journal-entries/",
    "/api/tax-codes/",
    "/api/banks/",
    "/api/cash-boxes/",
    "/api/custodies/",
    "/api/exchange-rates/",
    "/api/iban-requests/",
    "/api/bank-statements/import/",
    "/api/cash-counts/",
    "/api/parties/customers/",
    "/api/parties/suppliers/",
    "/api/parties/employees/",
    "/api/parties/affiliates/",
    "/api/vouchers/",
    "/api/assets/",
    "/api/legal-entities/",
    "/api/cost-centers/",
    "/api/roles/",
    "/api/attachments/",
    "/api/approval-rules/",
    "/api/users/",
]


@pytest.mark.django_db
def test_financial_endpoints_reject_with_arabic_only_messages(tenant_a, client_a):
    assert len(_EMPTY_PAYLOAD_400_PATHS) >= 25

    for path in _EMPTY_PAYLOAD_400_PATHS:
        response = client_a.post(path, {}, format="json")
        assert response.status_code == 400, f"{path}: expected 400, got {response.status_code}: {response.data}"
        _assert_all_arabic(response.data, path)


@pytest.mark.django_db
def test_permission_denied_message_is_arabic(tenant_a):
    from rest_framework.test import APIClient

    # A real user with zero roles — HasModulePermission denies every
    # permission_map-gated action for them (403), same as the 5.7 self-
    # approval message this file's other tests already cover for 403.
    powerless = UserFactory(tenant=tenant_a, email="powerless@arabic-sweep.test")
    client = APIClient()
    client.force_authenticate(user=powerless)

    response = client.post("/api/invoices/", {}, format="json")
    assert response.status_code == 403, response.data
    _assert_all_arabic(response.data, "/api/invoices/ (403, no role)")


@pytest.mark.django_db
def test_state_conflict_message_is_arabic(tenant_a, client_a):
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

    # CFO_REVIEW_1 C3: patching an issued invoice is a 409 state
    # conflict, not a 400 — already covered functionally by
    # tests/test_invoice_edit_void.py; this only re-checks the message
    # text is Arabic.
    response = client_a.patch(
        f"/api/invoices/{invoice['id']}/",
        {"customer": str(customer.id), "lines": []},
        format="json",
    )
    assert response.status_code == 409, response.data
    _assert_all_arabic(response.data, "/api/invoices/{id}/ PATCH after issue (409)")
