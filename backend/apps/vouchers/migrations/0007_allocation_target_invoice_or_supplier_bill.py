"""Sprint 8.2 (D7), step 1 of 2 — ADDITIVE. VoucherAllocation's target was a
hard FK to sales.Invoice; it becomes invoice OR supplier_bill (two nullable
FKs) with a CHECK that exactly one is set.

Schema only, no data written: every existing row already has its invoice
and the new column starts NULL, so every existing row already satisfies the
constraint. It is added NOT VALID here (enforced for every new or updated
row at once, existing rows not scanned); 0008 VALIDATEs it after the
reconciliation proof (docs/reports/2026-10-20-sprint8.2-allocation-migration.md).
"""
import django.db.models.deletion
from django.db import migrations, models

CHECK = (
    "(invoice_id IS NOT NULL AND supplier_bill_id IS NULL) "
    "OR (invoice_id IS NULL AND supplier_bill_id IS NOT NULL)"
)


class Migration(migrations.Migration):
    dependencies = [
        ("purchasing", "0002_supplier_bill"),
        ("sales", "0026_product_base_uom_product_category_and_more"),
        ("vouchers", "0006_voucher_deleted_at_voucher_deleted_by"),
    ]

    operations = [
        migrations.AlterField(
            model_name="voucherline",
            name="line_type",
            field=models.CharField(
                choices=[
                    ("invoice", "Invoice settlement"), ("bill", "Supplier bill settlement"),
                    ("on_account", "On account"), ("account", "Direct account"),
                ],
                max_length=10, verbose_name="line type",
            ),
        ),
        migrations.AddField(
            model_name="voucherline",
            name="supplier_bill",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="voucher_lines", to="purchasing.supplierbill",
            ),
        ),
        migrations.AddField(
            model_name="voucherallocation",
            name="supplier_bill",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="allocations", to="purchasing.supplierbill",
            ),
        ),
        migrations.AlterField(
            model_name="voucherallocation",
            name="invoice",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="allocations", to="sales.invoice",
            ),
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="voucherallocation",
                    constraint=models.CheckConstraint(
                        condition=(
                            models.Q(invoice__isnull=False, supplier_bill__isnull=True)
                            | models.Q(invoice__isnull=True, supplier_bill__isnull=False)
                        ),
                        name="voucherallocation_exactly_one_target",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=f"ALTER TABLE vouchers_voucherallocation ADD CONSTRAINT voucherallocation_exactly_one_target CHECK ({CHECK}) NOT VALID",
                    reverse_sql="ALTER TABLE vouchers_voucherallocation DROP CONSTRAINT voucherallocation_exactly_one_target",
                ),
            ],
        ),
    ]
