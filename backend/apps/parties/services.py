from apps.numbering.services import next_document_number
from apps.organization.models import CostCenter
from apps.organization.services import get_or_create_linked_cost_center

from .models import PartyRole

_DOC_TYPE_BY_ROLE = {
    PartyRole.Role.CUSTOMER: "party_customer",
    PartyRole.Role.SUPPLIER: "party_supplier",
    PartyRole.Role.EMPLOYEE: "party_employee",
    PartyRole.Role.AFFILIATE: "party_affiliate",
}


def link_employee_cost_center(party):
    """3.3 section 4: opt-in (default OFF, unlike vehicles) linked cost
    center for a Party's EMPLOYEE role."""
    return get_or_create_linked_cost_center(
        tenant=party.tenant,
        linked_object=party,
        code=f"CC-{party.code}",
        name=party.name,
        center_type=CostCenter.Type.EMPLOYEE,
    )


def generate_party_code(tenant, role):
    """Next party code, prefixed per role (3.4: CUS/SUP/EMP/AFF) — e.g.
    CUS-2026-00001. Atomic via apps.numbering (sprint 4.1; was
    COUNT-based and not safe under concurrent writes for the same
    tenant, ARCH_REVIEW_1.md debt #2). `legal_entity=None`: Party has
    no legal-entity dimension in this schema, so each role shares one
    sequence per tenant across every entity (see
    DocumentSequence.legal_entity's docstring)."""
    return next_document_number(tenant, _DOC_TYPE_BY_ROLE[role])
