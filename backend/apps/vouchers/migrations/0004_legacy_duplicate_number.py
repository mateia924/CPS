# Sprint 6.5.15 (UAT item 1): adds legacy_duplicate_number for
# uniformity with JournalEntry/Invoice — Voucher's own tenant-wide
# uniqueness constraint already existed before this sprint (no live
# tenant has ever had a duplicate voucher number), so the flagging
# below is defensive and expected to report zero.
from django.conf import settings
from django.db import migrations, models


def flag_duplicate_voucher_numbers(apps, schema_editor):
    Voucher = apps.get_model("vouchers", "Voucher")

    report = []
    duplicate_groups = (
        Voucher.objects.exclude(number="")
        .values("tenant_id", "number")
        .annotate(count=models.Count("id"))
        .filter(count__gt=1)
    )
    for group in duplicate_groups:
        entries = list(
            Voucher.objects.filter(tenant_id=group["tenant_id"], number=group["number"]).order_by("created_at", "id")
        )
        for voucher in entries[1:]:
            voucher.legacy_duplicate_number = True
            voucher.save(update_fields=["legacy_duplicate_number"])
        report.append({"tenant_id": str(group["tenant_id"]), "number": group["number"], "flagged": len(entries) - 1})

    print(f"[sprint 6.5.15 item 1] flagged legacy duplicate Voucher numbers: {report}")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounting', '0029_legacy_duplicate_number'),
        ('organization', '0005_legalentity_opening_approved_at'),
        ('parties', '0005_backfill_credit_limit_from_role_details'),
        ('tenants', '0014_tenant_default_legal_entity'),
        ('treasury', '0007_cash_count'),
        ('vouchers', '0003_alter_voucher_voucher_type'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='voucher',
            name='unique_voucher_number_per_tenant',
        ),
        migrations.AddField(
            model_name='voucher',
            name='legacy_duplicate_number',
            field=models.BooleanField(default=False, verbose_name='legacy duplicate number'),
        ),
        migrations.RunPython(flag_duplicate_voucher_numbers, noop),
        migrations.AddConstraint(
            model_name='voucher',
            constraint=models.UniqueConstraint(condition=models.Q(models.Q(('number', ''), _negated=True), ('legacy_duplicate_number', False)), fields=('tenant', 'number'), name='unique_voucher_number_per_tenant'),
        ),
    ]
