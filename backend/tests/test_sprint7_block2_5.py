"""Sprint 7.2.5 (docs/prompts/sprint-7.md §8.2, D11): serial numbers,
batches, batch stock, FEFO selection — models and services only, no
document/engine (that's 7.2.6/7.3). The tests this block's own plan
names explicitly.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.inventory.models import Batch, BatchStock, SerialNumber, Warehouse
from apps.inventory.services import is_batch_expired, select_fefo_batch
from apps.organization.models import LegalEntity

from .factories import ProductFactory


@pytest.mark.django_db
def test_duplicate_serial_for_the_same_tenant_and_item_is_rejected(tenant_a):
    item = ProductFactory(tenant=tenant_a)
    SerialNumber.objects.create(tenant=tenant_a, item=item, serial="IMEI-001")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            SerialNumber.objects.create(tenant=tenant_a, item=item, serial="IMEI-001")


@pytest.mark.django_db
def test_the_same_serial_string_on_a_different_item_is_allowed(tenant_a):
    """The decision's own scope is (tenant, item, serial) — not
    (tenant, serial) alone. A different item reusing the same string
    is a different physical thing and is not blocked."""
    item1 = ProductFactory(tenant=tenant_a)
    item2 = ProductFactory(tenant=tenant_a)
    SerialNumber.objects.create(tenant=tenant_a, item=item1, serial="SAME-001")
    SerialNumber.objects.create(tenant=tenant_a, item=item2, serial="SAME-001")

    assert SerialNumber.objects.filter(tenant=tenant_a, serial="SAME-001").count() == 2


@pytest.mark.django_db
def test_is_batch_expired_splits_exactly_on_the_given_date(tenant_a):
    item = ProductFactory(tenant=tenant_a)
    today = date(2026, 6, 15)
    not_expired = Batch.objects.create(tenant=tenant_a, item=item, number="B-FUTURE", expiry=today + timedelta(days=1))
    expires_today = Batch.objects.create(tenant=tenant_a, item=item, number="B-TODAY", expiry=today)
    expired = Batch.objects.create(tenant=tenant_a, item=item, number="B-PAST", expiry=today - timedelta(days=1))
    no_expiry = Batch.objects.create(tenant=tenant_a, item=item, number="B-NONE", expiry=None)

    assert is_batch_expired(not_expired, as_of=today) is False
    assert is_batch_expired(expires_today, as_of=today) is False  # expires_today's own date is not yet in the past
    assert is_batch_expired(expired, as_of=today) is True
    assert is_batch_expired(no_expiry, as_of=today) is False


@pytest.mark.django_db
def test_fefo_picks_the_soonest_expiring_non_expired_batch_with_stock(tenant_a):
    item = ProductFactory(tenant=tenant_a)
    entity = LegalEntity.objects.get(tenant=tenant_a, code="MAIN-01")
    warehouse = Warehouse.objects.create(tenant=tenant_a, legal_entity=entity, code="W1", name="مستودع")
    today = date(2026, 6, 15)

    expired_batch = Batch.objects.create(tenant=tenant_a, item=item, number="EXPIRED", expiry=today - timedelta(days=1))
    BatchStock.objects.create(tenant=tenant_a, batch=expired_batch, warehouse=warehouse, qty=Decimal("10"))

    far_batch = Batch.objects.create(tenant=tenant_a, item=item, number="FAR", expiry=today + timedelta(days=30))
    BatchStock.objects.create(tenant=tenant_a, batch=far_batch, warehouse=warehouse, qty=Decimal("5"))

    soon_batch = Batch.objects.create(tenant=tenant_a, item=item, number="SOON", expiry=today + timedelta(days=5))
    BatchStock.objects.create(tenant=tenant_a, batch=soon_batch, warehouse=warehouse, qty=Decimal("8"))

    empty_soonest_batch = Batch.objects.create(tenant=tenant_a, item=item, number="EMPTY", expiry=today + timedelta(days=1))
    BatchStock.objects.create(tenant=tenant_a, batch=empty_soonest_batch, warehouse=warehouse, qty=Decimal("0"))

    # No-expiry batch with real stock — proves NULLS LAST is explicit,
    # not an accident of which database engine happens to be running
    # (PostgreSQL's own ASC default is NULLS LAST, which looks correct
    # locally for the wrong reason; SQLite/MySQL both sort NULL first,
    # which would silently consume this undated batch BEFORE "soon"
    # if the ordering weren't forced with nulls_last=True).
    undated_batch = Batch.objects.create(tenant=tenant_a, item=item, number="UNDATED", expiry=None)
    BatchStock.objects.create(tenant=tenant_a, batch=undated_batch, warehouse=warehouse, qty=Decimal("20"))

    picked = select_fefo_batch(item, warehouse, Decimal("3"), as_of=today)

    assert picked.batch_id == soon_batch.id  # expired skipped, empty skipped, undated goes last, "FAR" is not the soonest


@pytest.mark.django_db
def test_fefo_tiebreak_between_batches_sharing_the_same_expiry_is_deterministic(tenant_a):
    """Two batches with the identical expiry date have no declared
    order otherwise — which one gets consumed would vary run to run.
    The earlier-created batch (Batch.created_at, confirmed to exist on
    the model before relying on it) wins the tie, deterministically."""
    item = ProductFactory(tenant=tenant_a)
    entity = LegalEntity.objects.get(tenant=tenant_a, code="MAIN-01")
    warehouse = Warehouse.objects.create(tenant=tenant_a, legal_entity=entity, code="W1", name="مستودع")
    same_expiry = date(2026, 6, 20)

    older_batch = Batch.objects.create(tenant=tenant_a, item=item, number="OLDER", expiry=same_expiry)
    BatchStock.objects.create(tenant=tenant_a, batch=older_batch, warehouse=warehouse, qty=Decimal("5"))

    newer_batch = Batch.objects.create(tenant=tenant_a, item=item, number="NEWER", expiry=same_expiry)
    BatchStock.objects.create(tenant=tenant_a, batch=newer_batch, warehouse=warehouse, qty=Decimal("5"))

    assert older_batch.created_at < newer_batch.created_at  # the fixture's own precondition, not assumed

    picked = select_fefo_batch(item, warehouse, Decimal("1"), as_of=date(2026, 6, 1))

    assert picked.batch_id == older_batch.id


@pytest.mark.django_db
def test_fefo_returns_none_when_only_expired_or_empty_batches_have_stock(tenant_a):
    item = ProductFactory(tenant=tenant_a)
    entity = LegalEntity.objects.get(tenant=tenant_a, code="MAIN-01")
    warehouse = Warehouse.objects.create(tenant=tenant_a, legal_entity=entity, code="W1", name="مستودع")
    today = date(2026, 6, 15)

    expired_batch = Batch.objects.create(tenant=tenant_a, item=item, number="EXPIRED", expiry=today - timedelta(days=1))
    BatchStock.objects.create(tenant=tenant_a, batch=expired_batch, warehouse=warehouse, qty=Decimal("10"))

    assert select_fefo_batch(item, warehouse, Decimal("1"), as_of=today) is None
