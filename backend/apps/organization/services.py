from django.utils.translation import gettext_lazy as _

from apps.access.services import user_is_owner

from .models import LegalEntity


def create_default_legal_entities(tenant, company_name):
    """Auto-created for every new tenant at registration (3.1): one
    COMPANY entity + one BRANCH under it. Also used by the Sprint 1 data
    migration to backfill tenants that existed before this sprint.
    """
    company = LegalEntity.objects.create(
        tenant=tenant,
        code="MAIN",
        name=company_name,
        entity_type=LegalEntity.Type.COMPANY,
    )
    branch = LegalEntity.objects.create(
        tenant=tenant,
        code="MAIN-01",
        name=_("Main Branch"),
        entity_type=LegalEntity.Type.BRANCH,
        parent=company,
        country_code=company.country_code,
        base_currency=company.base_currency,
    )
    return company, branch


def is_simplified_mode(tenant):
    """3.13: true only for exactly one company with exactly one branch
    and no holding at all — any holding, any second company, or any
    second branch takes the tenant out of simplified mode."""
    entities = list(LegalEntity.objects.filter(tenant=tenant, is_active=True))
    holdings = [e for e in entities if e.entity_type == LegalEntity.Type.HOLDING]
    companies = [e for e in entities if e.entity_type == LegalEntity.Type.COMPANY]
    branches = [e for e in entities if e.entity_type == LegalEntity.Type.BRANCH]
    return not holdings and len(companies) == 1 and len(branches) == 1


def default_branch_for_tenant(tenant):
    """The tenant's single branch, only when in simplified mode — used
    to auto-fill `legal_entity` on documents when the client omits it."""
    if not is_simplified_mode(tenant):
        return None
    return LegalEntity.objects.filter(
        tenant=tenant, entity_type=LegalEntity.Type.BRANCH, is_active=True
    ).first()


def get_accessible_entity_ids(user):
    """Every legal entity id `user` may see. An Owner sees every entity
    in their tenant. Anyone else sees the closure (entity + all
    descendants) of every entity granted via UserEntityAccess — access
    to a node implies access to everything under it (3.14 spirit: entity
    scoping, not a separate permission per node)."""
    if user_is_owner(user):
        return set(
            LegalEntity.objects.filter(tenant=user.tenant).values_list("id", flat=True)
        )

    from apps.access.models import UserEntityAccess

    granted_ids = set(
        UserEntityAccess.objects.filter(user=user).values_list("legal_entity_id", flat=True)
    )
    if not granted_ids:
        return set()

    all_entities = LegalEntity.objects.filter(tenant=user.tenant).values("id", "parent_id")
    children_map = {}
    for entity in all_entities:
        children_map.setdefault(entity["parent_id"], []).append(entity["id"])

    result = set()
    stack = list(granted_ids)
    while stack:
        entity_id = stack.pop()
        if entity_id in result:
            continue
        result.add(entity_id)
        stack.extend(children_map.get(entity_id, []))
    return result
