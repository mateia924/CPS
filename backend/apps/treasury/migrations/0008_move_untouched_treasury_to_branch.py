# Sprint 6.5.15 (UAT item 5): a simplified-mode tenant's bank/cash box/
# custody can end up registered on the COMPANY entity while every
# voucher now posts on the BRANCH (the exact live "fatma" shape before
# 6.5.14's default-entity fix) — the voucher's own treasury picker then
# has nothing to show for its own entity. Moves only accounts that are
# genuinely untouched (no Voucher has ever posted against them, on
# either side of a transfer) from the company to the tenant's one
# branch; anything with real history stays exactly where it is —
# "لا تعديل على أي مستند مرحَّل إطلاقًا". scripts/backup.sh runs before
# this migration, logged in docs/ops/backups.log.
from django.db import migrations


def _has_voucher_movement(Voucher, tenant_id, field_name, obj_id):
    return Voucher.objects.filter(tenant_id=tenant_id).filter(
        **{field_name: obj_id}
    ).exists() or Voucher.objects.filter(tenant_id=tenant_id).filter(**{f"counter_{field_name}": obj_id}).exists()


def move_untouched_treasury_to_branch(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    LegalEntity = apps.get_model("organization", "LegalEntity")
    Bank = apps.get_model("treasury", "Bank")
    CashBox = apps.get_model("treasury", "CashBox")
    Custody = apps.get_model("treasury", "Custody")
    Voucher = apps.get_model("vouchers", "Voucher")

    moved, stayed = [], []
    for tenant in Tenant.objects.all().iterator():
        entities = list(LegalEntity.objects.filter(tenant=tenant, is_active=True))
        holdings = [e for e in entities if e.entity_type == "holding"]
        companies = [e for e in entities if e.entity_type == "company"]
        branches = [e for e in entities if e.entity_type == "branch"]
        if holdings or len(companies) != 1 or len(branches) != 1:
            continue  # not simplified mode

        company, branch = companies[0], branches[0]
        for Model, field_name in ((Bank, "bank"), (CashBox, "cash_box"), (Custody, "custody")):
            for obj in Model.objects.filter(tenant=tenant, legal_entity=company):
                label = f"{tenant.subdomain}:{field_name}:{obj.name}"
                if _has_voucher_movement(Voucher, tenant.id, field_name, obj.id):
                    stayed.append(label)
                    continue
                obj.legal_entity = branch
                obj.save(update_fields=["legal_entity"])
                moved.append(label)

    print(f"[sprint 6.5.15 item 5] moved untouched company-entity treasury accounts to the branch: {moved}")
    print(f"[sprint 6.5.15 item 5] left in place (has real voucher history): {stayed}")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("treasury", "0007_cash_count"),
        ("organization", "0005_legalentity_opening_approved_at"),
        ("vouchers", "0004_legacy_duplicate_number"),
    ]

    operations = [
        migrations.RunPython(move_untouched_treasury_to_branch, noop),
    ]
