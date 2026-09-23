from django.db import migrations

# Sprint 5.5 (block 5.5.0, owner-approved 2026-09-23): the only place an
# IBAN was ever stored before this sprint was
# PartyRole.details["iban"] on a SUPPLIER role (SupplierPartySerializer,
# sprint 3.5) — a freely-editable value, never gated by approval.
# Copied here VERBATIM (no format/checksum validation — a placeholder
# value that would fail validate_iban today, e.g. "SA0000000000000000
# 000000", is deliberately carried over as-is; correcting it is exactly
# what forces it through IbanChangeRequest afterward, not a silent
# fixup during migration). `details["iban"]` itself is left untouched
# as a dead historical key — never read or written by the app again
# after this sprint (documented in README.md).


def backfill_iban(apps, schema_editor):
    PartyRole = apps.get_model("parties", "PartyRole")
    for role in PartyRole.objects.filter(role="supplier").exclude(details__iban="").exclude(
        details__iban__isnull=True
    ).select_related("party"):
        iban = role.details.get("iban")
        if not iban:
            continue
        role.party.iban = iban
        role.party.save(update_fields=["iban"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("parties", "0002_party_iban"),
    ]

    operations = [
        migrations.RunPython(backfill_iban, noop),
    ]
