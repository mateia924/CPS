from decimal import Decimal, InvalidOperation

from django.db import migrations

# Sprint 6.8 (F8, decision 16, same "IBAN precedent" as
# 0003_backfill_party_iban_from_role_details.py): the only place a
# credit limit was ever stored before this sprint was
# PartyRole.details["credit_limit"] on a CUSTOMER role (3.3's field
# table). Copied here verbatim (no re-validation — an unparsable
# historical value is simply skipped, not corrected). `details
# ["credit_limit"]` is left untouched as a dead historical key, never
# read or written by the app again after this sprint (documented in
# README.md).


def backfill_credit_limit(apps, schema_editor):
    PartyRole = apps.get_model("parties", "PartyRole")
    for role in PartyRole.objects.filter(role="customer").exclude(details__credit_limit__isnull=True):
        raw = role.details.get("credit_limit")
        if raw in (None, ""):
            continue
        try:
            role.credit_limit = Decimal(str(raw))
        except InvalidOperation:
            continue
        role.save(update_fields=["credit_limit"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("parties", "0004_party_building_number_party_city_party_district_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_credit_limit, noop),
    ]
