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


# Sprint 8.0: what 8.0 adds to a tenant's roles and approval rules. Both
# lists are read off the definitions registration itself uses —
# apps.access.services.DEFAULT_PERMISSIONS/SYSTEM_ROLES and
# apps.approvals.defaults.DEFAULT_APPROVAL_RULES — never restated here.
PURCHASING_DOC_TYPES = ("purchase_order", "supplier_bill", "purchase_return", "landed_cost", "party_netting")


def purchasing_permission_codes():
    from apps.access.services import DEFAULT_PERMISSIONS

    return [code for code, _description in DEFAULT_PERMISSIONS if code.startswith("purchasing.")]


def seed_purchasing_defaults(tenant):
    """Bring an existing tenant to what registration gives a new one for
    8.0: every system role holds its SYSTEM_ROLES share of the purchasing
    permissions, the Purchasing role exists, and the five purchasing
    approval rules (min_amount=0 -> Owner) exist. Idempotent: adds only
    what is missing, never removes or edits anything.

    Returns {"roles_created": [...], "permissions_added": {role: [codes]},
    "rules_created": [...], "roles_missing": [...]}. A system role other
    than Purchasing that the tenant no longer has is reported in
    roles_missing, not recreated: removing it was somebody's decision."""
    from apps.access.models import Permission, Role
    from apps.access.services import SYSTEM_ROLES, seed_permissions
    from apps.approvals.defaults import seed_default_approval_rules
    from apps.approvals.models import ApprovalRule

    seed_permissions()
    purchasing_codes = purchasing_permission_codes()
    result = {"roles_created": [], "permissions_added": {}, "rules_created": [], "roles_missing": []}

    for name, codes in SYSTEM_ROLES.items():
        wanted = [c for c in purchasing_codes if codes is None or c in codes]
        if not wanted:
            continue
        role = Role.objects.filter(tenant=tenant, name=name, is_system=True, deleted_at__isnull=True).first()
        if role is None:
            if name != "Purchasing":
                result["roles_missing"].append(name)
                continue
            role = Role.objects.create(tenant=tenant, name=name, is_system=True)
            result["roles_created"].append(name)
        held = set(role.permissions.filter(code__in=wanted).values_list("code", flat=True))
        missing = [c for c in wanted if c not in held]
        if missing:
            role.permissions.add(*Permission.objects.filter(code__in=missing))
            result["permissions_added"][name] = missing

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
