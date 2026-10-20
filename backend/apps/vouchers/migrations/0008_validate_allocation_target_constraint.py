"""Sprint 8.2 (D7), step 2 of 2 — TIGHTEN. Validates the exactly-one-target
CHECK that 0007 added NOT VALID, scanning every existing allocation. Run only
after the reconciliation proof showed every pre-existing allocation still
resolves to the same invoice, amount and voucher, and none has both targets
or neither (docs/reports/2026-10-20-sprint8.2-allocation-migration.md).
A row that broke the rule would stop this migration here, loudly."""
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("vouchers", "0007_allocation_target_invoice_or_supplier_bill")]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE vouchers_voucherallocation VALIDATE CONSTRAINT voucherallocation_exactly_one_target",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
