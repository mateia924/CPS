"""Sprint 4.2 (docs/SYSTEM_ANALYSIS.md 3.11/3.15.3; ARCH_REVIEW_1.md §1.2/
§3.2 — "أهم فجوة schema"): currency + exchange_rate on every
transaction line."""

from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounting.models import JournalEntry, TaxCode
from apps.accounting.services import (
    FX_ROUNDING_TOLERANCE,
    build_journal_lines_with_fx_rounding,
    post_invoice_journal_entry,
    seed_chart_of_accounts,
    seed_tax_codes_for_country,
)
from apps.organization.services import create_default_legal_entities
from apps.platform.models import AuditLog
from apps.sales.services import create_invoice
from apps.treasury.models import ExchangeRate
from apps.treasury.services import ExchangeRateNotFound, get_rate

from .factories import (
    LegalEntityFactory,
    PartyFactory,
    ProductFactory,
    TenantFactory,
)

# ---------------------------------------------------------------------
# apps.treasury.services.get_rate
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_get_rate_same_currency_is_always_1(db):
    tenant = TenantFactory()
    assert get_rate(tenant, "SAR", "SAR", date(2026, 1, 1)) == Decimal("1")


@pytest.mark.django_db
def test_get_rate_returns_most_recent_rate_on_or_before_date(db):
    tenant = TenantFactory()
    ExchangeRate.objects.create(
        tenant=tenant, from_currency="USD", to_currency="SAR", date=date(2026, 1, 1), rate=Decimal("3.75")
    )
    ExchangeRate.objects.create(
        tenant=tenant, from_currency="USD", to_currency="SAR", date=date(2026, 6, 1), rate=Decimal("3.80")
    )

    assert get_rate(tenant, "USD", "SAR", date(2026, 3, 1)) == Decimal("3.75")
    assert get_rate(tenant, "USD", "SAR", date(2026, 6, 1)) == Decimal("3.80")
    assert get_rate(tenant, "USD", "SAR", date(2026, 12, 31)) == Decimal("3.80")


@pytest.mark.django_db
def test_get_rate_never_uses_a_future_rate(db):
    tenant = TenantFactory()
    ExchangeRate.objects.create(
        tenant=tenant, from_currency="USD", to_currency="SAR", date=date(2026, 6, 1), rate=Decimal("3.80")
    )
    with pytest.raises(ExchangeRateNotFound):
        get_rate(tenant, "USD", "SAR", date(2026, 1, 1))


@pytest.mark.django_db
def test_get_rate_not_found_raises_with_arabic_message(db):
    tenant = TenantFactory()
    with pytest.raises(ExchangeRateNotFound) as exc_info:
        get_rate(tenant, "USD", "SAR", date(2026, 1, 1))
    assert "سعر صرف" in str(exc_info.value.message)


@pytest.mark.django_db
def test_get_rate_is_tenant_scoped(db):
    tenant_a = TenantFactory()
    tenant_b = TenantFactory()
    ExchangeRate.objects.create(
        tenant=tenant_a, from_currency="USD", to_currency="SAR", date=date(2026, 1, 1), rate=Decimal("3.75")
    )
    with pytest.raises(ExchangeRateNotFound):
        get_rate(tenant_b, "USD", "SAR", date(2026, 1, 1))


# ---------------------------------------------------------------------
# apps.accounting.services.build_journal_lines_with_fx_rounding
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_fx_rounding_helper_adds_no_line_when_exactly_balanced(db):
    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    entity = LegalEntityFactory(tenant=tenant)
    entry = JournalEntry.objects.create(tenant=tenant, legal_entity=entity, date=date(2026, 1, 1))
    from apps.accounting.models import Account

    ar = Account.objects.get(tenant=tenant, system_key="CASH")
    revenue = Account.objects.get(tenant=tenant, system_key="SALES")

    lines = build_journal_lines_with_fx_rounding(
        tenant,
        entry,
        [
            {"account": ar, "debit_fc": Decimal("100.00"), "credit_fc": Decimal("0")},
            {"account": revenue, "debit_fc": Decimal("0"), "credit_fc": Decimal("100.00")},
        ],
        Decimal("3.75"),
    )

    assert len(lines) == 2
    assert lines[0].debit_fc == Decimal("100.00")
    assert lines[0].debit == Decimal("375.00")
    assert lines[1].credit == Decimal("375.00")


@pytest.mark.django_db
def test_fx_rounding_helper_adds_a_rounding_line_when_gap_is_within_tolerance(db):
    from decimal import ROUND_HALF_UP

    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    entity = LegalEntityFactory(tenant=tenant)
    entry = JournalEntry.objects.create(tenant=tenant, legal_entity=entity, date=date(2026, 1, 1))
    from apps.accounting.models import Account

    ar = Account.objects.get(tenant=tenant, system_key="CASH")
    revenue = Account.objects.get(tenant=tenant, system_key="SALES")

    # One 100.00 fc debit line vs. three 33.33/33.33/33.34 fc credit
    # lines (fc-balanced: they sum to 100.00) — at rate 1.005, each
    # credit line's product lands just past the .xx5 rounding boundary
    # (33.33*1.005=33.49665 -> 33.50; 33.34*1.005=33.5067 -> 33.51) while
    # the single debit line's product doesn't (100.00*1.005=100.50
    # exactly) — the independently-rounded credit total (100.51) ends up
    # 0.01 off from the debit total (100.50), a real (small) rounding
    # gap. Expected values below are computed with the exact same
    # per-line rounding the implementation uses, so this test verifies
    # *behavior* (balance + correct rounding-line account/amount), not a
    # hand-picked constant.
    rate = Decimal("1.005")
    cents = Decimal("0.01")
    specs = [
        (ar, Decimal("100.00"), Decimal("0")),
        (revenue, Decimal("0"), Decimal("33.33")),
        (revenue, Decimal("0"), Decimal("33.33")),
        (revenue, Decimal("0"), Decimal("33.34")),
    ]
    expected_debit_total = sum(
        (fc_debit * rate).quantize(cents, rounding=ROUND_HALF_UP) for _a, fc_debit, _c in specs
    )
    expected_credit_total = sum(
        (fc_credit * rate).quantize(cents, rounding=ROUND_HALF_UP) for _a, _d, fc_credit in specs
    )
    expected_gap = expected_credit_total - expected_debit_total
    assert expected_gap != 0  # sanity: this rate must produce real rounding noise

    lines = build_journal_lines_with_fx_rounding(
        tenant, entry, [{"account": a, "debit_fc": d, "credit_fc": c} for a, d, c in specs], rate
    )

    debit_total = sum((line.debit for line in lines), Decimal("0"))
    credit_total = sum((line.credit for line in lines), Decimal("0"))
    assert debit_total == credit_total
    assert len(lines) == 5
    rounding_line = lines[4]
    assert rounding_line.account.system_key == "ROUNDING"
    if expected_gap > 0:
        assert rounding_line.debit == expected_gap
    else:
        assert rounding_line.credit == -expected_gap


@pytest.mark.django_db
def test_fx_rounding_helper_raises_when_gap_exceeds_tolerance(db):
    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    entity = LegalEntityFactory(tenant=tenant)
    entry = JournalEntry.objects.create(tenant=tenant, legal_entity=entity, date=date(2026, 1, 1))
    from apps.accounting.models import Account

    ar = Account.objects.get(tenant=tenant, system_key="CASH")
    revenue = Account.objects.get(tenant=tenant, system_key="SALES")

    with pytest.raises(ValueError):
        build_journal_lines_with_fx_rounding(
            tenant,
            entry,
            [
                {"account": ar, "debit_fc": Decimal("100.00"), "credit_fc": Decimal("0")},
                # Deliberately mismatched fc totals — not realistic
                # rounding noise, a real bug the helper must catch.
                {"account": revenue, "debit_fc": Decimal("0"), "credit_fc": Decimal("99.00")},
            ],
            Decimal("1"),
        )


def test_fx_rounding_tolerance_is_5_cents():
    assert FX_ROUNDING_TOLERANCE == Decimal("0.05")


# ---------------------------------------------------------------------
# Invoice -> posted journal entry, end to end: the literal spec test
# ("قيد بـ USD على كيان أساسه SAR بسعر 3.75 → debit_fc=100, debit=375")
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_usd_invoice_on_sar_entity_posts_correct_fc_and_base_amounts(db):
    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    company, entity = create_default_legal_entities(tenant, tenant.name)
    assert entity.base_currency == "SAR"
    ExchangeRate.objects.create(
        tenant=tenant, from_currency="USD", to_currency="SAR", date=date(2026, 1, 1), rate=Decimal("3.75")
    )
    seed_tax_codes_for_country(tenant, "SA")
    party = PartyFactory(tenant=tenant)
    product = ProductFactory(tenant=tenant, unit_price="100.00", tax_rate="0")
    tax_code_z = TaxCode.objects.get(tenant=tenant, code="Z")

    invoice = create_invoice(
        tenant=tenant,
        party=party,
        legal_entity=entity,
        issue_date=date(2026, 1, 1),
        line_inputs=[{"product": product, "quantity": Decimal("1"), "cost_center": None, "tax_code": tax_code_z}],
        currency="USD",
        exchange_rate=get_rate(tenant, "USD", "SAR", date(2026, 1, 1)),
    )

    assert invoice.total == Decimal("100.00")
    assert invoice.base_total == Decimal("375.00")

    entry = post_invoice_journal_entry(invoice)
    ar_line = entry.lines.get(account__party=party)
    revenue_line = entry.lines.get(account__system_key="SALES")

    assert ar_line.debit_fc == Decimal("100.00")
    assert ar_line.debit == Decimal("375.00")
    assert revenue_line.credit_fc == Decimal("100.00")
    assert revenue_line.credit == Decimal("375.00")


@pytest.mark.django_db
def test_changing_the_rate_later_does_not_affect_an_already_posted_entry(db):
    tenant = TenantFactory()
    seed_chart_of_accounts(tenant)
    _company, entity = create_default_legal_entities(tenant, tenant.name)
    ExchangeRate.objects.create(
        tenant=tenant, from_currency="USD", to_currency="SAR", date=date(2026, 1, 1), rate=Decimal("3.75")
    )
    seed_tax_codes_for_country(tenant, "SA")
    party = PartyFactory(tenant=tenant)
    product = ProductFactory(tenant=tenant, unit_price="100.00", tax_rate="0")
    tax_code_z = TaxCode.objects.get(tenant=tenant, code="Z")
    invoice = create_invoice(
        tenant=tenant,
        party=party,
        legal_entity=entity,
        issue_date=date(2026, 1, 1),
        line_inputs=[{"product": product, "quantity": Decimal("1"), "cost_center": None, "tax_code": tax_code_z}],
        currency="USD",
        exchange_rate=get_rate(tenant, "USD", "SAR", date(2026, 1, 1)),
    )
    entry = post_invoice_journal_entry(invoice)

    # A later, different rate must not retroactively change anything
    # already posted.
    ExchangeRate.objects.create(
        tenant=tenant, from_currency="USD", to_currency="SAR", date=date(2026, 6, 1), rate=Decimal("4.00")
    )

    entry.refresh_from_db()
    ar_line = entry.lines.get(account__party=party)
    assert entry.exchange_rate == Decimal("3.75000000")
    assert ar_line.debit == Decimal("375.00")


# ---------------------------------------------------------------------
# InvoiceCreateSerializer / API: currency defaulting, auto-pulled rate,
# missing-rate 400, explicit override + AuditLog.
# ---------------------------------------------------------------------


def _register_and_login(client, subdomain):
    register = client.post(
        "/api/auth/register/",
        {
            "company_name": "FX Test Co",
            "subdomain": subdomain,
            "email": f"owner@{subdomain}.test",
            "password": "S3curePass!2026",
        },
        format="json",
    )
    assert register.status_code == 201
    login = client.post(
        "/api/auth/login/",
        {"subdomain": subdomain, "email": f"owner@{subdomain}.test", "password": "S3curePass!2026"},
        format="json",
    )
    assert login.status_code == 200
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    return login.data["tenant"]["id"]


@pytest.mark.django_db
def test_invoice_defaults_to_base_currency_with_rate_1(db):
    client = APIClient()
    _register_and_login(client, "fx-default")
    from apps.tenants.models import Tenant

    tenant = Tenant.objects.get(subdomain="fx-default")
    party = PartyFactory(tenant=tenant)
    product = ProductFactory(tenant=tenant, unit_price="50.00", tax_rate="0")
    tax_code_z = TaxCode.objects.get(tenant=tenant, code="Z")

    response = client.post(
        "/api/invoices/",
        {
            "customer": str(party.id),
            "lines": [{"product": str(product.id), "quantity": "1", "tax_code": str(tax_code_z.id)}],
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.data["currency"] == "SAR"
    assert Decimal(response.data["exchange_rate"]) == Decimal("1.00000000")
    assert Decimal(response.data["base_total"]) == Decimal("50.00")


@pytest.mark.django_db
def test_invoice_in_foreign_currency_without_a_rate_returns_400(db):
    client = APIClient()
    _register_and_login(client, "fx-missing-rate")
    from apps.tenants.models import Tenant

    tenant = Tenant.objects.get(subdomain="fx-missing-rate")
    party = PartyFactory(tenant=tenant)
    product = ProductFactory(tenant=tenant, unit_price="50.00", tax_rate="0")
    tax_code_z = TaxCode.objects.get(tenant=tenant, code="Z")

    response = client.post(
        "/api/invoices/",
        {
            "customer": str(party.id),
            "currency": "USD",
            "lines": [{"product": str(product.id), "quantity": "1", "tax_code": str(tax_code_z.id)}],
        },
        format="json",
    )

    assert response.status_code == 400
    assert "exchange_rate" in response.data


@pytest.mark.django_db
def test_invoice_auto_pulls_rate_when_currency_differs_from_base(db):
    client = APIClient()
    _register_and_login(client, "fx-autopull")
    from apps.tenants.models import Tenant

    tenant = Tenant.objects.get(subdomain="fx-autopull")
    ExchangeRate.objects.create(
        tenant=tenant, from_currency="USD", to_currency="SAR", date=date(2026, 1, 1), rate=Decimal("3.75")
    )
    party = PartyFactory(tenant=tenant)
    product = ProductFactory(tenant=tenant, unit_price="100.00", tax_rate="0")
    tax_code_z = TaxCode.objects.get(tenant=tenant, code="Z")

    response = client.post(
        "/api/invoices/",
        {
            "customer": str(party.id),
            "currency": "USD",
            "issue_date": "2026-01-01",
            "lines": [{"product": str(product.id), "quantity": "1", "tax_code": str(tax_code_z.id)}],
        },
        format="json",
    )

    assert response.status_code == 201
    assert Decimal(response.data["exchange_rate"]) == Decimal("3.75000000")
    assert Decimal(response.data["base_total"]) == Decimal("375.00")


@pytest.mark.django_db
def test_manual_exchange_rate_override_is_logged_to_audit_log(db):
    client = APIClient()
    tenant_id = _register_and_login(client, "fx-override")
    from apps.tenants.models import Tenant

    tenant = Tenant.objects.get(subdomain="fx-override")
    ExchangeRate.objects.create(
        tenant=tenant, from_currency="USD", to_currency="SAR", date=date(2026, 1, 1), rate=Decimal("3.75")
    )
    party = PartyFactory(tenant=tenant)
    product = ProductFactory(tenant=tenant, unit_price="100.00", tax_rate="0")
    tax_code_z = TaxCode.objects.get(tenant=tenant, code="Z")

    response = client.post(
        "/api/invoices/",
        {
            "customer": str(party.id),
            "currency": "USD",
            "exchange_rate": "3.90",
            "issue_date": "2026-01-01",
            "lines": [{"product": str(product.id), "quantity": "1", "tax_code": str(tax_code_z.id)}],
        },
        format="json",
    )

    assert response.status_code == 201
    assert Decimal(response.data["exchange_rate"]) == Decimal("3.90000000")
    override_entry = AuditLog.objects.get(
        tenant_id=tenant_id, action="invoice.exchange_rate_overridden", target_id=response.data["id"]
    )
    assert override_entry.after["exchange_rate"] == "3.90000000"


@pytest.mark.django_db
def test_same_currency_explicit_rate_override_is_ignored(db):
    client = APIClient()
    _register_and_login(client, "fx-sameccy")
    from apps.tenants.models import Tenant

    tenant = Tenant.objects.get(subdomain="fx-sameccy")
    party = PartyFactory(tenant=tenant)
    product = ProductFactory(tenant=tenant, unit_price="10.00", tax_rate="0")
    tax_code_z = TaxCode.objects.get(tenant=tenant, code="Z")

    response = client.post(
        "/api/invoices/",
        {
            "customer": str(party.id),
            "currency": "SAR",
            "exchange_rate": "5.00",
            "lines": [{"product": str(product.id), "quantity": "1", "tax_code": str(tax_code_z.id)}],
        },
        format="json",
    )

    assert response.status_code == 201
    assert Decimal(response.data["exchange_rate"]) == Decimal("1.00000000")


# ---------------------------------------------------------------------
# ExchangeRate model/screen: uniqueness, tenant isolation, permissions.
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_exchange_rate_unique_per_tenant_pair_and_date(db):
    tenant = TenantFactory()
    ExchangeRate.objects.create(
        tenant=tenant, from_currency="USD", to_currency="SAR", date=date(2026, 1, 1), rate=Decimal("3.75")
    )
    from django.db import IntegrityError

    with pytest.raises(IntegrityError):
        ExchangeRate.objects.create(
            tenant=tenant, from_currency="USD", to_currency="SAR", date=date(2026, 1, 1), rate=Decimal("3.80")
        )


@pytest.mark.django_db
def test_exchange_rate_screen_create_and_tenant_isolation(db):
    client = APIClient()
    _register_and_login(client, "fx-screen")

    create = client.post(
        "/api/exchange-rates/",
        {"from_currency": "USD", "to_currency": "SAR", "date": "2026-01-01", "rate": "3.75"},
        format="json",
    )
    assert create.status_code == 201
    assert create.data["source"] == "manual"

    other_client = APIClient()
    _register_and_login(other_client, "fx-screen-other")
    other_list = other_client.get("/api/exchange-rates/")
    assert other_list.data["count"] == 0
