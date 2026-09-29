# Sprint 6.5.14: fixes the legal_entity_ids[0] bug (README/SYSTEM_
# ANALYSIS.md §11, 2026-09-29) — a real, deterministic per-tenant
# default entity instead of the frontend guessing from an alphabetically
# -sorted UUID list. Backfill sets it to the tenant's own BRANCH entity
# (never the company/holding row — a real accountant works "in a
# branch", the company row is a legal-structure node, not a workspace)
# for every EXISTING tenant that has exactly one active branch, which
# is every live tenant checked before this migration was written (§11
# decision log has the full inventory). A tenant with zero or more than
# one branch is left null — apps.accounts.views.MeView's own
# deterministic fallback (BRANCH type first, then by name) covers that
# case at read time; this migration only sets a *preference*, never
# invents one where the data itself doesn't clearly suggest it.
#
# Deliberately does NOT move, reassign, or touch a single document —
# Fatma's own split (15 journal entries on her branch; one voucher, one
# asset, one depreciation schedule on her company) stays exactly as it
# is. This migration only sets which entity a *new* user's/form's
# default should be, never who owns which existing row (migrations
# never import live app code — plain queries only, same convention as
# every other data migration in this project).
import django.db.models.deletion
from django.db import migrations, models


def backfill_default_legal_entity(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    LegalEntity = apps.get_model("organization", "LegalEntity")
    for tenant in Tenant.objects.all().iterator():
        branches = list(LegalEntity.objects.filter(tenant=tenant, entity_type="branch", is_active=True))
        if len(branches) == 1:
            tenant.default_legal_entity = branches[0]
            tenant.save(update_fields=["default_legal_entity"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("organization", "0005_legalentity_opening_approved_at"),
        ("tenants", "0013_tenantfeatures_cost_center_required_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="default_legal_entity",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="organization.legalentity",
            ),
        ),
        migrations.RunPython(backfill_default_legal_entity, noop),
    ]
