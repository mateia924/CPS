"""The default ApprovalRule set every tenant is born with — ONE definition,
read by both tenant registration (apps.accounts.serializers) and the
historical backfill migrations (approvals/0002, 0005, 0007, 0009, 0011,
0013, 0015, 0019).

Why one place: until 7.4 each default lived only in the migration that
backfilled it, while registration hard-coded journal_entry + iban_change.
Every tenant registered after 0007/0009/0011/0013/0015/0019 was therefore
born without the opening_balance, recurring_entry, asset_* and stock_*
rules (found by 7.4's e2e — docs/SYSTEM_ANALYSIS.md §11).

Deliberately free of model imports: migrations pass their historical
models in, registration passes the real ones. A migration asking for a
doc_type this definition no longer holds raises, so removing a default
here fails a fresh migrate loudly instead of drifting silently.
"""

# doc_type -> system role name required to approve. Every default rule is
# min_amount=0, active. iban_change/opening_balance are additionally the
# fixed, non-deletable ones (approvals.views._LOCKED_DOC_TYPES).
DEFAULT_APPROVAL_RULES = {
    "journal_entry": "Owner",  # 0002 — sprint 4.5, 3.15.9
    "iban_change": "Owner",  # 0005 — sprint 5.5, CFO_REVIEW_1 C10 (fixed)
    "opening_balance": "Owner",  # 0007 — sprint 6.3, 3.16.3 (fixed)
    "recurring_entry": "Owner",  # 0009 — sprint 6.4, decision 9
    "asset_depreciation": "Owner",  # 0011 — sprint 6.5, decision 11
    "asset_addition": "Owner",  # 0013 — sprint 6.5, decision 11
    "asset_disposal": "Owner",  # 0015 — sprint 6.5, decision 11
    "stock_receipt": "Owner",  # 0019 — sprint 7.0, D5
    "stock_issue": "Owner",  # 0019
    "stock_transfer": "Owner",  # 0019
    "stock_count": "Owner",  # 0019
    # Sprint 8.0 (D3): registration only — no backfill migration onto
    # existing tenants (owner's call per tenant, backfill_default_approval_rules).
    "purchase_order": "Owner",
    "supplier_bill": "Owner",
    "purchase_return": "Owner",
    "landed_cost": "Owner",
    "party_netting": "Owner",
}


def _checked(doc_types):
    wanted = list(DEFAULT_APPROVAL_RULES) if doc_types is None else list(doc_types)
    missing = [d for d in wanted if d not in DEFAULT_APPROVAL_RULES]
    if missing:
        raise KeyError(f"Not in DEFAULT_APPROVAL_RULES: {missing}")
    return wanted


def seed_default_approval_rules(tenant, *, ApprovalRule, Role, doc_types=None):
    """get_or_create each default rule (min_amount=0, active) for `tenant`.
    `doc_types=None` means the full set (registration). Skips the tenant
    when it has no system role of the required name — the migrations'
    original behaviour for a tenant whose roles were never seeded."""
    for doc_type in _checked(doc_types):
        role = Role.objects.filter(tenant=tenant, name=DEFAULT_APPROVAL_RULES[doc_type], is_system=True).first()
        if role is None:
            continue
        ApprovalRule.objects.get_or_create(
            tenant=tenant, doc_type=doc_type, min_amount=0,
            defaults={"required_role": role, "is_active": True},
        )


def backfill_default_approval_rules(apps, doc_types):
    """The backfill migrations' body: `doc_types` (the ones that migration
    historically introduced) on every existing tenant, with the migration's
    historical models. Checked BEFORE the tenant loop, so a definition that
    lost one of them fails even a fresh migrate with no tenants at all."""
    doc_types = _checked(doc_types)
    Tenant = apps.get_model("tenants", "Tenant")
    Role = apps.get_model("access", "Role")
    ApprovalRule = apps.get_model("approvals", "ApprovalRule")
    for tenant in Tenant.objects.all().iterator():
        seed_default_approval_rules(tenant, ApprovalRule=ApprovalRule, Role=Role, doc_types=doc_types)
