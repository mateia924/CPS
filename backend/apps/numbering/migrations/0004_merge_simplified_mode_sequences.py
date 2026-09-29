# Sprint 6.5.15 (UAT item 1): apps.numbering.services.next_document_number
# now shares ONE DocumentSequence per (tenant, doc_type, year) whenever
# the displayed number won't carry an entity code — previously every
# entity kept its own independent counter regardless, so two entities
# both showing no code (the small-client simplified-mode default) could
# issue the exact same displayed number (the live "JV-2026-00001" bug
# on both "fatma"'s company and branch). Existing sequences for such
# (tenant, doc_type) pairs are merged here — no document is moved or
# renumbered, only the *next* counter value going forward. Migrations
# never import live app code (project convention): the automatic
# include_entity_code rule (branch_count > 1) is duplicated inline,
# exactly matching apps.numbering.services.next_document_number.
from django.db import migrations


def merge_sequences_with_no_entity_code(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    LegalEntity = apps.get_model("organization", "LegalEntity")
    DocumentSequence = apps.get_model("numbering", "DocumentSequence")
    DocumentNumberingSetting = apps.get_model("numbering", "DocumentNumberingSetting")

    merged_report = []
    for tenant in Tenant.objects.all().iterator():
        entity_scoped = list(DocumentSequence.objects.filter(tenant=tenant, legal_entity__isnull=False))
        if not entity_scoped:
            continue

        branch_count = LegalEntity.objects.filter(
            tenant=tenant, entity_type="branch", is_active=True
        ).count()
        overrides = {
            setting.doc_type: setting.include_entity_code
            for setting in DocumentNumberingSetting.objects.filter(tenant=tenant)
            if setting.include_entity_code is not None
        }

        groups = {}
        for seq in entity_scoped:
            include_entity_code = overrides.get(seq.doc_type, branch_count > 1)
            if include_entity_code:
                continue  # unaffected — every entity keeps its own sequence
            groups.setdefault((seq.doc_type, seq.year), []).append(seq)

        for (doc_type, year), seqs in groups.items():
            merged_last_number = max(s.last_number for s in seqs)
            shared, _created = DocumentSequence.objects.get_or_create(
                tenant=tenant, doc_type=doc_type, legal_entity=None, year=year,
                defaults={"last_number": merged_last_number},
            )
            if not _created and shared.last_number < merged_last_number:
                shared.last_number = merged_last_number
                shared.save(update_fields=["last_number"])
            DocumentSequence.objects.filter(id__in=[s.id for s in seqs]).delete()
            merged_report.append(
                {
                    "tenant": tenant.subdomain, "doc_type": doc_type, "year": year,
                    "merged_from": [(str(s.legal_entity_id), s.last_number) for s in seqs],
                    "merged_into": merged_last_number,
                }
            )

    print(f"[sprint 6.5.15 item 1] merged document sequences with no entity code: {merged_report}")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("numbering", "0003_documentnumberingsetting_include_entity_code"),
        ("organization", "0005_legalentity_opening_approved_at"),
    ]

    operations = [
        migrations.RunPython(merge_sequences_with_no_entity_code, noop),
    ]
