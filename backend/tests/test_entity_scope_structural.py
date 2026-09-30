"""Sprint 6.6.1 (item 3): a structural, introspection-based guard that
every ViewSet whose model reaches a legal entity — directly (a
`legal_entity` field on the model itself) or by a declared indirect
relation (`INDIRECT_ENTITY_MODELS` below) — inherits `EntityScopedMixin`
(or the full `EntityScopedViewSet`), the same "walk urlpatterns, fail
loudly on anything unclassified" shape as `test_structural_isolation.
py`'s own `TENANT_FILTER_EXEMPTIONS` (ARCH_REVIEW_1). A new ViewSet
added in a future sprint whose model has a direct `legal_entity` field
is automatically picked up and must inherit the mixin or be added to
`ENTITY_SCOPE_EXEMPTIONS` with a real reason — never silently skipped.
"""

from django.urls import get_resolver

from apps.common.viewsets import EntityScopedMixin

# ViewSets whose model reaches a legal entity but are deliberately NOT
# entity-scoped — every entry needs a real reason, reviewed by a human
# each time one is added. (No entries today: every model with a direct
# `legal_entity` field that has its own ViewSet is scoped — see the
# sprint 6.6.1 block in docs/sprints/6.6-summary.md. `PartyRole.
# legal_entity` — descriptive metadata on a role assignment, not a
# document — is the kind of thing that would go here if it ever got
# its own top-level ViewSet; it doesn't today, so there's nothing to
# exempt. `IbanChangeRequestViewSet`'s own target is a GenericFK to
# Bank or Party — no single ORM lookup path reaches a legal entity
# across both — but since `IbanChangeRequest` has no direct
# `legal_entity` field, the automatic check below never flags it in
# the first place; its own reasoning is recorded in
# test_structural_isolation.py's TENANT_FILTER_EXEMPTIONS instead.)
ENTITY_SCOPE_EXEMPTIONS = {}

# Models with NO direct `legal_entity` field but a declared indirect
# relation to one, each needing its own ViewSet to set a non-default
# `entity_lookup` — the automatic direct-field check below can't find
# these on its own ("بعلاقة معلنة", sprint 6.6.1 item 3's own wording:
# a DECLARED relation, not something auto-detected).
INDIRECT_ENTITY_MODELS = {
    "apps.assets.models.AssetDisposal": "asset__legal_entity_id",
    "apps.treasury.models.BankStatement": "bank__legal_entity_id",
    "apps.treasury.models.BankStatementLine": "statement__bank__legal_entity_id",
    "apps.treasury.models.CashCount": "cash_box__legal_entity_id",
    "apps.accounting.models.RecurringInstallment": "entry__legal_entity_id",
}


def _qualified_name(cls):
    return f"{cls.__module__}.{cls.__name__}"


def _qualified_model_name(model):
    return f"{model.__module__}.{model.__name__}"


def _registered_view_classes():
    """Every distinct view class backing a registered URL, found via
    Django's own resolver — same helper as test_structural_isolation.py."""

    def walk(patterns):
        classes = []
        for pattern in patterns:
            if hasattr(pattern, "url_patterns"):
                classes.extend(walk(pattern.url_patterns))
            else:
                cls = getattr(pattern.callback, "cls", None)
                if cls is not None:
                    classes.append(cls)
        return classes

    seen = {}
    for cls in walk(get_resolver().url_patterns):
        seen[_qualified_name(cls)] = cls
    return seen


def _model_for(cls):
    """The model a ViewSet's queryset/serializer targets, or None for
    a plain APIView (no model at all — never reaches a legal entity by
    definition, so it's simply never flagged below)."""
    queryset = getattr(cls, "queryset", None)
    if queryset is not None:
        return queryset.model
    serializer_class = getattr(cls, "serializer_class", None)
    meta = getattr(serializer_class, "Meta", None) if serializer_class else None
    return getattr(meta, "model", None)


def _reaches_legal_entity(model):
    """True if `model` has a direct `legal_entity` field, or is
    LegalEntity itself (the row IS the entity), or is one of
    INDIRECT_ENTITY_MODELS's own declared indirect relations."""
    if model is None:
        return False
    if _qualified_model_name(model) == "apps.organization.models.LegalEntity":
        return True
    if _qualified_model_name(model) in INDIRECT_ENTITY_MODELS:
        return True
    try:
        model._meta.get_field("legal_entity")
    except Exception:
        return False
    return True


def test_every_registered_entity_reaching_view_is_scoped_or_exempted():
    classes = _registered_view_classes()
    for name in ENTITY_SCOPE_EXEMPTIONS:
        assert name in classes, (
            f"{name} is listed in ENTITY_SCOPE_EXEMPTIONS but no longer "
            "exists as a registered view — remove the stale entry."
        )

    violations = []
    for name, cls in classes.items():
        model = _model_for(cls)
        if not _reaches_legal_entity(model):
            continue
        if name in ENTITY_SCOPE_EXEMPTIONS:
            continue
        if not issubclass(cls, EntityScopedMixin):
            violations.append(name)

    assert not violations, (
        "View(s) reach a legal entity (directly or by a declared "
        "indirect relation) but don't inherit EntityScopedMixin/"
        "EntityScopedViewSet and aren't in ENTITY_SCOPE_EXEMPTIONS — "
        f"add each to apps/common/viewsets.py's mixin or to this file's "
        f"exemptions with a reason: {violations}"
    )
