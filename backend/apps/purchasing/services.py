import json
from decimal import Decimal, InvalidOperation

from apps.accounting.services import COMPLIANCE_DIR

from .models import WithholdingTaxCode


class WithholdingTableError(ValueError):
    """A compliance/<country>/withholding.json entry that cannot be loaded
    as written — raised before any row is created, so a bad table never
    half-loads."""


def withholding_table(country_code):
    """The entries of apps/compliance/<country>/withholding.json, checked.
    [] for a country with no table yet (same as seed_tax_codes_for_country:
    no compliance package = nothing to seed, not an error)."""
    path = COMPLIANCE_DIR / country_code.lower() / "withholding.json"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        entries = json.load(f)
    bases = set(WithholdingTaxCode.Base.values)
    applies = set(WithholdingTaxCode.AppliesTo.values)
    codes = set()
    for entry in entries:
        where = f"{path.parent.name}/withholding.json, code {entry.get('code')!r}"
        if not entry.get("code") or not entry.get("name_ar"):
            raise WithholdingTableError(f"{where}: code and name_ar are required.")
        if entry["code"] in codes:
            raise WithholdingTableError(f"{where}: duplicate code.")
        codes.add(entry["code"])
        try:
            rate = Decimal(str(entry["rate"]))
        except (KeyError, InvalidOperation):
            raise WithholdingTableError(f"{where}: rate is missing or not a number.") from None
        if not Decimal("0") <= rate <= Decimal("100"):
            raise WithholdingTableError(f"{where}: rate {rate} is outside 0-100.")
        if entry.get("base") not in bases:
            raise WithholdingTableError(f"{where}: base must be one of {sorted(bases)}.")
        if entry.get("applies_to") not in applies:
            raise WithholdingTableError(f"{where}: applies_to must be one of {sorted(applies)}.")
    return entries


def load_withholding_codes(tenant, country_code):
    """Idempotent: creates each code of the country's table the tenant
    doesn't have yet, as an example (is_example=True). An existing row —
    approved by the owner, rate edited, deactivated — is never touched.
    Returns the number of codes created."""
    country = country_code.upper()
    created = 0
    for entry in withholding_table(country):
        _code, was_created = WithholdingTaxCode.objects.get_or_create(
            tenant=tenant,
            country=country,
            code=entry["code"],
            defaults={
                "name_ar": entry["name_ar"],
                "rate": Decimal(str(entry["rate"])),
                "base": entry["base"],
                "applies_to": entry["applies_to"],
                "is_example": True,
            },
        )
        created += was_created
    return created


def tenant_country_codes(tenant):
    """Every country the tenant's legal entities sit in — the countries
    whose withholding tables apply to it."""
    from apps.organization.models import LegalEntity

    return sorted(set(LegalEntity.objects.filter(tenant=tenant).values_list("country_code", flat=True)))


# Sprint 8.0: purchasing's approval types; the permission codes and the
# Purchasing role's share are read off apps.access.services
# (DEFAULT_PERMISSIONS/SYSTEM_ROLES), never restated here.
PURCHASING_DOC_TYPES = ("purchase_order", "supplier_bill", "purchase_return", "landed_cost", "party_netting")


def purchasing_permission_codes():
    from apps.access.services import DEFAULT_PERMISSIONS

    return [code for code, _description in DEFAULT_PERMISSIONS if code.startswith("purchasing.")]


# The four system accounts D1 added for purchasing.
PURCHASING_SYSTEM_KEYS = ("WHT_PAYABLE", "PURCHASE_PRICE_VARIANCE", "LANDED_COST_CLEARING", "SUPPLIER_ADVANCES")


def seed_purchasing_defaults(tenant):
    """ADDITIVE ONLY (owner decision 2026-10-20). Purchasing is not released:
    nothing a tenant's users can do changes because this ran. It creates
    what is missing and never edits, adds to, or removes anything that
    exists — in particular it touches NO existing role. The owner grants
    purchasing deliberately on the roles screen.

    Creates, each only if absent:
      - the purchasing system accounts (D1) — creation only; an existing
        account is never touched (unlike add_missing_system_accounts, which
        also corrects allow_manual_posting);
      - the withholding codes of the tenant's countries, as examples (D6);
      - the purchasing.* rows of the global permission catalog (get_or_create,
        never update: an existing row's description is left alone);
      - the Purchasing system role with purchasing.view/manage and no users;
        an existing Purchasing role is left exactly as it is;
      - the five purchasing approval rules (min_amount=0 -> Owner). Not a
        role change: a document type with no rule is approved automatically
        (the 7.4 incident), so the rule is the safe default.

    Returns {"accounts_created", "wht_created", "permissions_created",
    "roles_created", "rules_created", "rules_not_active"}."""
    from apps.access.models import Permission, Role
    from apps.access.services import DEFAULT_PERMISSIONS, SYSTEM_ROLES
    from apps.accounting.management.commands.add_missing_system_accounts import (
        Command as AccountsCommand,
    )
    from apps.accounting.models import Account
    from apps.accounting.services import SYSTEM_ACCOUNT_SPECS
    from apps.approvals.defaults import seed_default_approval_rules
    from apps.approvals.models import ApprovalRule

    result = {
        "accounts_created": [], "wht_created": {}, "permissions_created": [], "roles_created": [],
        "rules_created": [], "rules_not_active": [],
    }

    accounts = AccountsCommand()
    for spec in SYSTEM_ACCOUNT_SPECS:
        if spec["system_key"] not in PURCHASING_SYSTEM_KEYS:
            continue
        if Account.objects.filter(tenant=tenant, system_key=spec["system_key"]).exists():
            continue
        outcome, detail = accounts._ensure_account(tenant, spec)
        if outcome != "created":
            raise ValueError(f"could not create {spec['system_key']}: {detail}")
        result["accounts_created"].append(f"{spec['system_key']} {detail}")

    for country in tenant_country_codes(tenant):
        created = load_withholding_codes(tenant, country)
        if created:
            result["wht_created"][country] = created

    for code, description in DEFAULT_PERMISSIONS:
        if code.startswith("purchasing."):
            _row, created = Permission.objects.get_or_create(code=code, defaults={"description": description})
            if created:
                result["permissions_created"].append(code)

    if not Role.objects.filter(tenant=tenant, name="Purchasing").exists():
        role = Role.objects.create(tenant=tenant, name="Purchasing", is_system=True)
        role.permissions.set(Permission.objects.filter(code__in=SYSTEM_ROLES["Purchasing"]))
        result["roles_created"].append("Purchasing")

    def active_rules():
        return set(
            ApprovalRule.objects.filter(
                tenant=tenant, doc_type__in=PURCHASING_DOC_TYPES, is_active=True, deleted_at__isnull=True
            ).values_list("doc_type", flat=True)
        )

    before = active_rules()
    seed_default_approval_rules(tenant, ApprovalRule=ApprovalRule, Role=Role, doc_types=PURCHASING_DOC_TYPES)
    result["rules_created"] = sorted(active_rules() - before)
    result["rules_not_active"] = sorted(set(PURCHASING_DOC_TYPES) - active_rules())
    return result
