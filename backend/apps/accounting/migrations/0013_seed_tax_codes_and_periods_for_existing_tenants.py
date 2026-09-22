# Sprint 4.6 (3.11/3.16.2): "حزمة الامتثال السعودية ... تُبذر لكل
# مستأجر سعودي عند التسجيل ولكل الحاليين عبر migration". Every existing
# tenant's default (first) legal entity's country_code drives which
# package seeds — every legal entity defaults to "SA" in this project,
# so in practice this seeds every existing tenant. Also generates the
# current calendar year's tax periods for each tenant's legal entities
# (3.16.2: "توليد تلقائي للسنة الحالية").
import calendar
import json
from datetime import date
from pathlib import Path

from django.db import migrations
from django.utils import timezone

COMPLIANCE_DIR = Path(__file__).resolve().parent.parent.parent / "compliance"


def _seed_tax_codes(apps, tenant, country_code):
    Account = apps.get_model("accounting", "Account")
    TaxCode = apps.get_model("accounting", "TaxCode")

    path = COMPLIANCE_DIR / country_code.lower() / "tax_codes.json"
    if not path.exists():
        return
    with path.open(encoding="utf-8") as f:
        codes = json.load(f)
    for entry in codes:
        account = None
        if entry.get("system_key"):
            account = Account.objects.filter(tenant=tenant, system_key=entry["system_key"]).first()
        TaxCode.objects.get_or_create(
            tenant=tenant,
            code=entry["code"],
            defaults={
                "name": entry["name"],
                "rate": entry["rate"],
                "kind": entry["kind"],
                "direction": entry["direction"],
                "deductible": entry["deductible"],
                "account": account,
                "country_code": country_code,
            },
        )


def _generate_tax_periods(apps, legal_entity, year):
    TaxPeriod = apps.get_model("accounting", "TaxPeriod")
    if legal_entity.tax_period_type == "quarterly":
        ranges = [(1, 3), (4, 6), (7, 9), (10, 12)]
    else:
        ranges = [(m, m) for m in range(1, 13)]
    for start_month, end_month in ranges:
        start = date(year, start_month, 1)
        end = date(year, end_month, calendar.monthrange(year, end_month)[1])
        TaxPeriod.objects.get_or_create(
            tenant=legal_entity.tenant,
            legal_entity=legal_entity,
            start=start,
            end=end,
            defaults={"period_type": legal_entity.tax_period_type},
        )


def seed_existing_tenants(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    LegalEntity = apps.get_model("organization", "LegalEntity")

    current_year = timezone.now().year
    for tenant in Tenant.objects.all().iterator():
        entities = list(LegalEntity.objects.filter(tenant=tenant, is_active=True))
        if not entities:
            continue
        _seed_tax_codes(apps, tenant, entities[0].country_code)
        for entity in entities:
            _generate_tax_periods(apps, entity, current_year)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0012_taxcode_taxperiod"),
        ("organization", "0003_legalentity_tax_period_type"),
    ]

    operations = [
        migrations.RunPython(seed_existing_tenants, noop),
    ]
