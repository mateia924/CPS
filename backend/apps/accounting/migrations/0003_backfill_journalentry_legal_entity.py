from django.db import migrations


def backfill_journalentry_legal_entity(apps, schema_editor):
    JournalEntry = apps.get_model("accounting", "JournalEntry")
    LegalEntity = apps.get_model("organization", "LegalEntity")
    Invoice = apps.get_model("sales", "Invoice")

    default_branch_by_tenant = {}

    def default_branch(tenant_id):
        if tenant_id not in default_branch_by_tenant:
            default_branch_by_tenant[tenant_id] = (
                LegalEntity.objects.filter(tenant_id=tenant_id, entity_type="branch", is_active=True)
                .order_by("code")
                .first()
            )
        return default_branch_by_tenant[tenant_id]

    for entry in JournalEntry.objects.filter(legal_entity__isnull=True):
        branch = None
        # Prefer the source invoice's own (already-backfilled) entity so
        # a journal entry always matches the document that produced it,
        # rather than independently guessing "the tenant's first branch"
        # a second time.
        if entry.source_type == "invoice" and entry.source_id:
            invoice = Invoice.objects.filter(id=entry.source_id).first()
            if invoice is not None:
                branch = invoice.legal_entity

        if branch is None:
            branch = default_branch(entry.tenant_id)

        if branch is None:
            raise RuntimeError(
                f"No branch found for tenant {entry.tenant_id} while backfilling "
                f"JournalEntry.legal_entity — organization.0002 should have created one."
            )

        entry.legal_entity = branch
        entry.save(update_fields=["legal_entity"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0002_journalentry_legal_entity_journalline_cost_center"),
        ("organization", "0002_backfill_default_entities"),
        ("sales", "0003_backfill_invoice_legal_entity"),
    ]

    operations = [
        migrations.RunPython(backfill_journalentry_legal_entity, noop),
    ]
