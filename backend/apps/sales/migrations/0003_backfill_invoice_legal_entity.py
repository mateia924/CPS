from django.db import migrations


def backfill_invoice_legal_entity(apps, schema_editor):
    Invoice = apps.get_model("sales", "Invoice")
    LegalEntity = apps.get_model("organization", "LegalEntity")

    for invoice in Invoice.objects.filter(legal_entity__isnull=True).select_related("tenant"):
        branch = (
            LegalEntity.objects.filter(tenant=invoice.tenant, entity_type="branch", is_active=True)
            .order_by("code")
            .first()
        )
        if branch is None:
            # Should be unreachable: organization.0002 backfills a branch
            # for every tenant before this migration runs. Fail loudly
            # rather than silently leaving a NULL that the next
            # migration's NOT NULL constraint would reject anyway.
            raise RuntimeError(
                f"No branch found for tenant {invoice.tenant_id} while backfilling "
                f"Invoice.legal_entity — organization.0002 should have created one."
            )
        invoice.legal_entity = branch
        invoice.save(update_fields=["legal_entity"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0002_invoice_legal_entity_invoiceline_cost_center"),
        ("organization", "0002_backfill_default_entities"),
    ]

    operations = [
        migrations.RunPython(backfill_invoice_legal_entity, noop),
    ]
