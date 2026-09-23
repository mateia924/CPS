"""Sprint 6.0 (docs/prompts/sprint-6.md, block 6.0): post-UAT fixes not
already covered by tests/test_arabic_messages.py — status_label/journal
entry link on invoices, JWT logout blacklist, PAST_DUE -> SUSPENDED
grace-period beat, and the stale-FX-rate warning on invoice creation.
"""

from datetime import timedelta

import pytest
from rest_framework.test import APIClient

from apps.tenants.models import Tenant
from apps.tenants.tasks import auto_suspend_past_due_tenants
from apps.treasury.models import ExchangeRate

from .factories import PartyFactory, ProductFactory, TenantFactory, UserFactory

PASSWORD = "TestPass!2026"


def _create_invoice(client, tenant, currency=None):
    from apps.accounting.models import TaxCode

    customer = PartyFactory(tenant=tenant)
    product = ProductFactory(tenant=tenant)
    tax_code = TaxCode.objects.get(tenant=tenant, code="Z")
    payload = {
        "customer": str(customer.id),
        "lines": [{"product": str(product.id), "quantity": "1", "tax_code": str(tax_code.id)}],
    }
    if currency:
        payload["currency"] = currency
    return client.post("/api/invoices/", payload, format="json")


def _issue_invoice(client, tenant, currency=None):
    created = _create_invoice(client, tenant, currency=currency)
    assert created.status_code == 201, created.data
    return client.post(f"/api/invoices/{created.data['id']}/issue/")


@pytest.mark.django_db
def test_invoice_status_label_and_journal_entry_link(tenant_a, client_a):
    issued = _issue_invoice(client_a, tenant_a)
    assert issued.status_code == 200, issued.data
    assert issued.data["status_label"]
    assert issued.data["journal_entry_id"]
    assert issued.data["journal_entry_number"]

    detail = client_a.get(f"/api/invoices/{issued.data['id']}/")
    assert detail.data["journal_entry_id"] == issued.data["journal_entry_id"]
    assert detail.data["journal_entry_number"] == issued.data["journal_entry_number"]


@pytest.mark.django_db
def test_invoice_with_stale_exchange_rate_returns_warning(tenant_a, client_a):
    # Sprint 6.0 item 6 / CFO_REVIEW_1 C14: rate resolved from a row
    # older than STALE_RATE_DAYS=7 (apps.treasury.services) warns, never
    # blocks. "Today" in this environment is 2026-09-23; a rate dated
    # 2026-09-01 is 22 days old. The rate is resolved (and the warning
    # raised) at *create* time, not issue() — issue()'s own response
    # doesn't carry a warnings key at all (apps/sales/views.py).
    ExchangeRate.objects.create(
        tenant=tenant_a, from_currency="USD", to_currency="SAR", date="2026-09-01", rate="3.75"
    )
    created = _create_invoice(client_a, tenant_a, currency="USD")
    assert created.status_code == 201, created.data
    assert any("سعر الصرف" in w for w in created.data["warnings"])


@pytest.mark.django_db
def test_refresh_token_is_blacklisted_after_logout():
    tenant = TenantFactory(subdomain="logout-test")
    UserFactory(tenant=tenant, email="user@logout-test.test", password=PASSWORD)
    client = APIClient()

    login = client.post(
        "/api/auth/login/",
        {"subdomain": "logout-test", "email": "user@logout-test.test", "password": PASSWORD},
        format="json",
    )
    assert login.status_code == 200, login.data
    access, refresh = login.data["access"], login.data["refresh"]

    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    logout = client.post("/api/auth/logout/", {"refresh": refresh}, format="json")
    assert logout.status_code == 204

    refreshed = APIClient().post("/api/auth/refresh/", {"refresh": refresh}, format="json")
    assert refreshed.status_code == 401


@pytest.mark.django_db
def test_past_due_tenant_auto_suspends_after_grace_period(settings):
    settings.PAST_DUE_GRACE_DAYS = 14
    from django.utils import timezone

    overdue = TenantFactory(
        subdomain="past-due-overdue",
        status=Tenant.Status.PAST_DUE,
        past_due_since=timezone.now() - timedelta(days=15),
    )
    within_grace = TenantFactory(
        subdomain="past-due-within-grace",
        status=Tenant.Status.PAST_DUE,
        past_due_since=timezone.now() - timedelta(days=5),
    )

    count = auto_suspend_past_due_tenants()

    overdue.refresh_from_db()
    within_grace.refresh_from_db()
    assert count == 1
    assert overdue.status == Tenant.Status.SUSPENDED
    assert within_grace.status == Tenant.Status.PAST_DUE
