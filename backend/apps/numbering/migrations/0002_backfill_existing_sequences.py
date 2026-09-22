from collections import Counter

from django.db import migrations

# Sprint 4.1: old numbers stay exactly as they are (Invoice "INV-0007",
# Party "P-0012") — the new format (e.g. "INV-2026-00008",
# "CUS-2026-00001") can never textually collide with the old one, so
# this migration's only job is making the *next* number issued for each
# new scope start after whatever already exists there, not literally
# reproduce the old flat counters (which had no legal_entity/year or
# per-role dimension to backfill into in the first place — the old
# scheme was tenant-wide only).
DOC_TYPE_BY_ROLE = {
    "customer": "party_customer",
    "supplier": "party_supplier",
    "employee": "party_employee",
    "affiliate": "party_affiliate",
}


def backfill_invoice_sequences(apps, schema_editor):
    Invoice = apps.get_model("sales", "Invoice")
    DocumentSequence = apps.get_model("numbering", "DocumentSequence")

    counts = Counter()
    for tenant_id, legal_entity_id, issue_date in Invoice.objects.values_list(
        "tenant_id", "legal_entity_id", "issue_date"
    ):
        counts[(tenant_id, legal_entity_id, issue_date.year)] += 1

    for (tenant_id, legal_entity_id, year), count in counts.items():
        DocumentSequence.objects.update_or_create(
            tenant_id=tenant_id,
            doc_type="invoice",
            legal_entity_id=legal_entity_id,
            year=year,
            defaults={"last_number": count},
        )


def backfill_party_sequences(apps, schema_editor):
    PartyRole = apps.get_model("parties", "PartyRole")
    DocumentSequence = apps.get_model("numbering", "DocumentSequence")

    # reset_yearly defaults to True and no DocumentNumberingSetting row
    # exists yet for any tenant at this point — the first real call to
    # next_document_number() will lazily create one and use the actual
    # current year as the scope key, so the backfill must use that same
    # "now" year, not each role's oldest/newest creation date.
    from django.utils import timezone

    current_year = timezone.localdate().year

    counts = Counter()
    for tenant_id, role in PartyRole.objects.values_list("party__tenant_id", "role"):
        doc_type = DOC_TYPE_BY_ROLE.get(role)
        if doc_type:
            counts[(tenant_id, doc_type)] += 1

    for (tenant_id, doc_type), count in counts.items():
        DocumentSequence.objects.update_or_create(
            tenant_id=tenant_id,
            doc_type=doc_type,
            legal_entity=None,
            year=current_year,
            defaults={"last_number": count},
        )


def backfill_all(apps, schema_editor):
    backfill_invoice_sequences(apps, schema_editor)
    backfill_party_sequences(apps, schema_editor)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("numbering", "0001_initial"),
        ("sales", "0009_invoice_party_not_null"),
        ("parties", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(backfill_all, noop),
    ]
