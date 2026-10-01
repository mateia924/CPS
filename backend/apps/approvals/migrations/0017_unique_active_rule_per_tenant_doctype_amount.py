# Sprint 6.6.5 (item 3): a DB-level uniqueness guarantee on
# (tenant, doc_type, min_amount) among ACTIVE, non-deleted rules —
# a tenant previously had no guard at all against configuring two
# active rules for the exact same document type/threshold (which one
# `get_matching_rule` picks between is undefined). Any pre-existing
# live duplicate is deactivated here first (keeping the earliest as
# canonical, same "flag/deactivate the newer one, never touch amounts/
# dates" precedent as accounting/migrations/0029_legacy_duplicate_
# number.py), with a printed report, so the constraint below can be
# added without failing and this can never silently recur.
from django.conf import settings
from django.db import migrations, models


def deactivate_duplicate_approval_rules(apps, schema_editor):
    ApprovalRule = apps.get_model("approvals", "ApprovalRule")

    report = []
    duplicate_groups = (
        ApprovalRule.objects.filter(is_active=True, deleted_at__isnull=True)
        .values("tenant_id", "doc_type", "min_amount")
        .annotate(count=models.Count("id"))
        .filter(count__gt=1)
    )
    for group in duplicate_groups:
        rules = list(
            ApprovalRule.objects.filter(
                tenant_id=group["tenant_id"], doc_type=group["doc_type"], min_amount=group["min_amount"],
                is_active=True, deleted_at__isnull=True,
            ).order_by("created_at", "id")
        )
        # Keep the earliest (canonical) active; deactivate every later
        # duplicate — metadata only, never a change to min_amount/
        # required_role on any of them.
        for rule in rules[1:]:
            rule.is_active = False
            rule.save(update_fields=["is_active"])
        report.append(
            {
                "tenant_id": str(group["tenant_id"]), "doc_type": group["doc_type"],
                "min_amount": str(group["min_amount"]), "deactivated": len(rules) - 1,
            }
        )

    print(f"[sprint 6.6.5 item 3] deactivated duplicate active ApprovalRule rows: {report}")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("approvals", "0016_approvalrule_deleted_at_approvalrule_deleted_by"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(deactivate_duplicate_approval_rules, noop),
        migrations.AddConstraint(
            model_name="approvalrule",
            constraint=models.UniqueConstraint(
                condition=models.Q(is_active=True, deleted_at__isnull=True),
                fields=("tenant", "doc_type", "min_amount"),
                name="unique_approval_rule_active_per_tenant_doctype_amount",
            ),
        ),
    ]
