# Sprint 6.5.15 (UAT item 1): adds legacy_duplicate_number for
# uniformity with JournalEntry/Voucher — Invoice's own tenant-wide
# uniqueness constraint already existed before this sprint (no live
# tenant has ever had a duplicate invoice number), so the flagging
# below is defensive and expected to report zero.
from django.conf import settings
from django.db import migrations, models


def flag_duplicate_invoice_numbers(apps, schema_editor):
    Invoice = apps.get_model("sales", "Invoice")

    report = []
    duplicate_groups = (
        Invoice.objects.exclude(number="")
        .values("tenant_id", "number")
        .annotate(count=models.Count("id"))
        .filter(count__gt=1)
    )
    for group in duplicate_groups:
        entries = list(
            Invoice.objects.filter(tenant_id=group["tenant_id"], number=group["number"]).order_by("created_at", "id")
        )
        for invoice in entries[1:]:
            invoice.legacy_duplicate_number = True
            invoice.save(update_fields=["legacy_duplicate_number"])
        report.append({"tenant_id": str(group["tenant_id"]), "number": group["number"], "flagged": len(entries) - 1})

    print(f"[sprint 6.5.15 item 1] flagged legacy duplicate Invoice numbers: {report}")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('organization', '0005_legalentity_opening_approved_at'),
        ('parties', '0005_backfill_credit_limit_from_role_details'),
        ('sales', '0021_invoice_is_post_delivery_void'),
        ('tenants', '0014_tenant_default_legal_entity'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='invoice',
            name='unique_invoice_number_per_tenant',
        ),
        migrations.AddField(
            model_name='invoice',
            name='legacy_duplicate_number',
            field=models.BooleanField(default=False, verbose_name='legacy duplicate number'),
        ),
        migrations.RunPython(flag_duplicate_invoice_numbers, noop),
        migrations.AddConstraint(
            model_name='invoice',
            constraint=models.UniqueConstraint(condition=models.Q(models.Q(('number', ''), _negated=True), ('legacy_duplicate_number', False)), fields=('tenant', 'number'), name='unique_invoice_number_per_tenant'),
        ),
    ]
