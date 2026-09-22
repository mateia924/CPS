# Sprint 4.6 (3.16.2, rule 16): "Migration: كل بند قديم بنسبة 15 -> S،
# 0 -> Z". The literal spec assumes only those two rates ever existed;
# real data on this dev server also has 14%/10% test rows (pre-4.6
# manual test invoices with ad-hoc tax_rate values, not the standard
# 15%). Generalized here to "any nonzero rate -> S, zero -> Z" instead
# of failing/mis-mapping those rows — a reasonable, documented
# extension of the literal rule rather than silently wrong data (see
# the Decision Log). Depends on accounting.0013 having already seeded
# S/Z for every existing tenant.
from django.db import migrations


def backfill_tax_code(apps, schema_editor):
    InvoiceLine = apps.get_model("sales", "InvoiceLine")
    TaxCode = apps.get_model("accounting", "TaxCode")

    code_cache = {}  # (tenant_id, code) -> TaxCode
    for line in InvoiceLine.objects.select_related("invoice").filter(tax_code__isnull=True).iterator():
        tenant_id = line.invoice.tenant_id
        code = "S" if line.tax_rate > 0 else "Z"
        key = (tenant_id, code)
        if key not in code_cache:
            code_cache[key] = TaxCode.objects.filter(tenant_id=tenant_id, code=code).first()
        tax_code = code_cache[key]
        if tax_code is not None:
            InvoiceLine.objects.filter(pk=line.pk).update(tax_code=tax_code)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0014_invoiceline_tax_code_product_default_tax_code"),
        ("accounting", "0013_seed_tax_codes_and_periods_for_existing_tenants"),
    ]

    operations = [
        migrations.RunPython(backfill_tax_code, noop),
    ]
