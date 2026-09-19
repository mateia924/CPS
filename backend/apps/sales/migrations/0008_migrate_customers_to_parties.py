from django.db import migrations

# docs/SYSTEM_ANALYSIS.md 3.3 (sprint 3): every existing Customer row
# becomes a Party with a CUSTOMER role, and every existing Invoice is
# re-pointed at the new Party (Invoice.legacy_customer, renamed in
# 0007, is left untouched — historical reference only). Approved by
# the user before running against real existing data (6 customers, 4
# invoices, 5 tenants including the real "Acme Trading" — see the
# session this was approved in / Decision Log).


def migrate_customers_to_parties(apps, schema_editor):
    Customer = apps.get_model("sales", "Customer")
    Invoice = apps.get_model("sales", "Invoice")
    Party = apps.get_model("parties", "Party")
    PartyRole = apps.get_model("parties", "PartyRole")

    for customer in Customer.objects.all():
        # Same count()+1 sequential-code scheme as
        # apps.parties.services.generate_party_code — duplicated here
        # rather than imported (migrations must not depend on live app
        # code that can drift from the schema this migration was
        # written against).
        count = Party.objects.filter(tenant_id=customer.tenant_id).count()
        party = Party.objects.create(
            tenant_id=customer.tenant_id,
            code=f"P-{count + 1:04d}",
            name=customer.name,
            party_type="organization",
            email=customer.email,
            phone=customer.phone,
            tax_number=customer.tax_number,
            address={"raw": customer.address} if customer.address else {},
            country_code="SA",
            default_currency="SAR",
            is_active=customer.is_active,
        )
        PartyRole.objects.create(party=party, role="customer", is_active=True, details={})
        Invoice.objects.filter(legacy_customer_id=customer.id).update(party_id=party.id)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0007_rename_customer_to_legacy_customer"),
        ("parties", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(migrate_customers_to_parties, noop_reverse),
    ]
