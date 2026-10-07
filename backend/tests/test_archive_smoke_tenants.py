"""§11 standing rule (added alongside this command): every session that
creates a temporary smoke-* tenant ends with `manage.py
archive_smoke_tenants`. One test: it archives a smoke-* tenant and
never touches any other.

Sprint 7.0.2 follow-up: a historical audit found 19 already-archived
smoke-* tenants silently carrying POSTED, never-reversed JournalEntry
rows — this command used to archive a tenant's status without ever
looking at its books. The tests below prove the new guard actually
refuses (rule 11: proven by first checking the guard fails loudly,
not just that it appears present), that --force without --reason is
itself refused, and that --force with --reason archives anyway and
logs it.
"""

import pytest
from django.core.management import CommandError, call_command

from apps.accounting.models import JournalEntry
from apps.platform.models import AuditLog
from apps.tenants.models import Tenant

from .factories import LegalEntityFactory, TenantFactory


@pytest.mark.django_db
def test_archives_only_smoke_prefixed_tenants():
    smoke_tenant = TenantFactory(subdomain="smoke-1790421727")
    other_tenant = TenantFactory(subdomain="regular-co")

    call_command("archive_smoke_tenants")

    smoke_tenant.refresh_from_db()
    other_tenant.refresh_from_db()
    assert smoke_tenant.status == Tenant.Status.ARCHIVED
    assert other_tenant.status == Tenant.Status.ACTIVE


@pytest.mark.django_db
def test_refuses_to_archive_a_tenant_with_an_unreversed_posted_entry():
    tenant = TenantFactory(subdomain="smoke-unreversed")
    entity = LegalEntityFactory(tenant=tenant)
    entry = JournalEntry.objects.create(
        tenant=tenant, legal_entity=entity, date="2026-01-01",
        number="JV-TEST-0001", status=JournalEntry.Status.POSTED,
        produced_by=JournalEntry.ProducedBy.MANUAL,
    )

    with pytest.raises(CommandError) as excinfo:
        call_command("archive_smoke_tenants")

    assert "smoke-unreversed" in str(excinfo.value)
    assert entry.number in str(excinfo.value)
    tenant.refresh_from_db()
    assert tenant.status == Tenant.Status.ACTIVE  # refusal must not partially archive


@pytest.mark.django_db
def test_force_without_reason_is_refused():
    tenant = TenantFactory(subdomain="smoke-forceonly")
    entity = LegalEntityFactory(tenant=tenant)
    JournalEntry.objects.create(
        tenant=tenant, legal_entity=entity, date="2026-01-01",
        number="JV-TEST-0002", status=JournalEntry.Status.POSTED,
        produced_by=JournalEntry.ProducedBy.MANUAL,
    )

    with pytest.raises(CommandError):
        call_command("archive_smoke_tenants", force=True)

    tenant.refresh_from_db()
    assert tenant.status == Tenant.Status.ACTIVE


@pytest.mark.django_db
def test_force_with_reason_archives_anyway_and_logs_it():
    tenant = TenantFactory(subdomain="smoke-forcedreason")
    entity = LegalEntityFactory(tenant=tenant)
    entry = JournalEntry.objects.create(
        tenant=tenant, legal_entity=entity, date="2026-01-01",
        number="JV-TEST-0003", status=JournalEntry.Status.POSTED,
        produced_by=JournalEntry.ProducedBy.MANUAL,
    )

    call_command("archive_smoke_tenants", force=True, reason="owner-authorized debt, see sprint 7.0.2 audit")

    tenant.refresh_from_db()
    assert tenant.status == Tenant.Status.ARCHIVED
    log = AuditLog.objects.get(
        tenant_id=tenant.id, action="tenant.archive_smoke_forced_with_unreversed_entries",
    )
    assert entry.number in log.before["unreversed_entry_numbers"]
    assert log.after["reason"] == "owner-authorized debt, see sprint 7.0.2 audit"


@pytest.mark.django_db
def test_a_clean_tenant_with_no_journal_entries_still_archives_without_force():
    tenant = TenantFactory(subdomain="smoke-clean")

    call_command("archive_smoke_tenants")

    tenant.refresh_from_db()
    assert tenant.status == Tenant.Status.ARCHIVED


@pytest.mark.django_db
def test_a_tenant_with_a_cleanly_reversed_entry_still_archives_without_force():
    """Sprint 7.0.3: the command used to filter on status=POSTED alone
    (apps.accounting.services.unreversed_posted_entries' definition),
    which would wrongly count the REVERSAL entry itself — also POSTED
    by construction — as unresolved debt, blocking a tenant that was
    actually closed cleanly. Switching to debt_entries
    (reverses__isnull=True) fixes this: the reversal is excluded, only
    a genuinely un-reversed forward entry would still block."""
    tenant = TenantFactory(subdomain="smoke-cleanlyreversed")
    entity = LegalEntityFactory(tenant=tenant)
    original = JournalEntry.objects.create(
        tenant=tenant, legal_entity=entity, date="2026-01-01",
        number="JV-TEST-0004", status=JournalEntry.Status.REVERSED,
        produced_by=JournalEntry.ProducedBy.MANUAL,
    )
    JournalEntry.objects.create(
        tenant=tenant, legal_entity=entity, date="2026-01-02",
        number="JV-TEST-0004-R", status=JournalEntry.Status.POSTED, reverses=original,
        produced_by=JournalEntry.ProducedBy.MANUAL,
    )

    call_command("archive_smoke_tenants")

    tenant.refresh_from_db()
    assert tenant.status == Tenant.Status.ARCHIVED
