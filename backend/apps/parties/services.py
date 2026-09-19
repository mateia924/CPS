from apps.organization.models import CostCenter
from apps.organization.services import get_or_create_linked_cost_center

from .models import Party


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


def generate_party_code(tenant):
    """Next sequential party code for a tenant, e.g. P-0001.

    TECH DEBT (README "Technical debt"): same count()+1 pattern as
    apps.sales.services.generate_invoice_number — not safe under
    concurrent writes for the same tenant. Acceptable for MVP
    single-writer usage.
    """
    count = Party.objects.filter(tenant=tenant).count()
    return f"P-{count + 1:04d}"
