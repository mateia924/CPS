from django.contrib.contenttypes.models import ContentType
from django.utils.translation import gettext_lazy as _

from apps.access.services import user_is_owner

from .models import CostCenter, LegalEntity


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


def get_or_create_linked_cost_center(tenant, linked_object, code, name, center_type):
    """docs/SYSTEM_ANALYSIS.md 3.2/sprint 3 section 4: "مركز التكلفة
    المرتبط يأخذ نفس الاسم ونوعه المناسب ولا يُنشأ مرتين" — looked up by
    (tenant, content type, object id) first, using CostCenter.linked_object
    (a GenericFK seeded in sprint 1 as forward-compatible plumbing, first
    actually used here). `code` must already be unique per tenant (the
    caller derives it from the linked object's own code)."""
    content_type = ContentType.objects.get_for_model(linked_object)
    existing = CostCenter.objects.filter(
        tenant=tenant, linked_content_type=content_type, linked_object_id=linked_object.id
    ).first()
    if existing is not None:
        return existing
    return CostCenter.objects.create(
        tenant=tenant,
        code=code,
        name=name,
        center_type=center_type,
        linked_content_type=content_type,
        linked_object_id=linked_object.id,
    )


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


def default_legal_entity_id_for_user(user, accessible_ids):
    """Sprint 6.5.14 (fix: legal_entity_ids[0] was sorted by UUID
    string — arbitrary re: entity_type, unrelated to which entity a
    tenant's documents actually live on). Deterministic and documented:
    1. Tenant.default_legal_entity if it's one of `user`'s own
       accessible entities (an Owner always passes this check; a
       restricted user only if they were actually granted it).
    2. Otherwise the first of `accessible_ids`, ordered BRANCH type
       first, then by name — never by id/creation order.
    None if `accessible_ids` is empty (no entity at all)."""
    if not accessible_ids:
        return None

    tenant_default_id = user.tenant.default_legal_entity_id
    if tenant_default_id and tenant_default_id in accessible_ids:
        return tenant_default_id

    from django.db.models import Case, When

    fallback = (
        LegalEntity.objects.filter(id__in=accessible_ids)
        .order_by(Case(When(entity_type=LegalEntity.Type.BRANCH, then=0), default=1), "name")
        .first()
    )
    return fallback.id if fallback else None


_COMPANY_PROFILE_FIELDS = (
    "commercial_registration", "building_number", "street", "district",
    "city", "postal_code", "short_address", "phone", "email",
)


def effective_company_profile(legal_entity):
    """Sprint 5.6 (block 5.6): "عنوان مهيكل ... لكل كيان قانوني قيمه
    الخاصة مع وراثة من الشركة الأم" — a blank field on `legal_entity`
    falls back to the nearest ancestor that has it set, field by field
    (not "inherit the whole profile or none of it" — a branch can
    override just its own street while still inheriting the parent's
    commercial registration, tax number and phone)."""
    result = {}
    for field in _COMPANY_PROFILE_FIELDS:
        node = legal_entity
        value = ""
        while node is not None:
            value = getattr(node, field)
            if value:
                break
            node = node.parent
        result[field] = value
    return result
