"""Sprint 6.6.5 (owner decision 29 Sept, unified delete rule): "لا
DELETE فعلي في أي مكان" is meant as a STRUCTURAL guarantee, not a
per-model promise that has to be re-verified by hand every time a new
ViewSet is added — a plain `ModelViewSet`/`DestroyModelMixin` subclass
that forgets to opt into `apps.common.viewsets.SoftDeleteViewSetMixin`
or `SoftDeleteDocumentViewSetMixin` silently gets DRF's own default
`destroy()` (a real SQL DELETE) the moment it's reachable, exactly the
live gap this block found and fixed twice already (AttachmentRule,
Role — see git history for this sprint). This test walks the REAL
urlconf (not a hand-maintained list of ViewSets) so it can't go stale.
"""

from django.urls import get_resolver

from apps.common.viewsets import SoftDeleteDocumentViewSetMixin, SoftDeleteViewSetMixin

# A bespoke (not mixin-based) `destroy()` override is allowed ONLY when
# listed here with a reason that's actually been verified — never a
# silent exemption. Each entry's own `destroy()` must still soft-delete
# (deleted_at/deleted_by) and never fall through to a real DELETE.
_BESPOKE_SOFT_DELETE_ALLOWLIST = {
    "apps.accounting.views.OpeningBalanceViewSet": (
        "delegates to apps.accounting.opening_balances."
        "delete_opening_balance_entry, its own bespoke-but-compliant "
        "soft delete from sprint 6.6.3d, predating the shared mixin"
    ),
    "apps.access.views.RoleViewSet": (
        "extra is_system/M2M-users guards layered on top of the same "
        "Collector-based PROTECT check + soft delete, sprint 6.6.5"
    ),
    "apps.accounting.views.FiscalYearViewSet": (
        "eligibility isn't a document `status` or a PROTECT-walkable "
        "FK (documents reach a fiscal year by DATE RANGE, not FK) — "
        "apps.accounting.periods.fiscal_year_emptiness_reason is its "
        "own explicit, shared 'completely empty' check + soft delete, "
        "sprint 6.6.5 §6.2"
    ),
}


def _iter_viewset_classes():
    seen = set()

    def walk(patterns):
        for pattern in patterns:
            nested = getattr(pattern, "url_patterns", None)
            if nested is not None:
                walk(nested)
                continue
            cls = getattr(getattr(pattern, "callback", None), "cls", None)
            if cls is not None and cls not in seen:
                seen.add(cls)
                yield cls

    yield from walk(get_resolver().url_patterns)


def test_every_destroy_capable_viewset_goes_through_soft_delete():
    violations = []
    for cls in _iter_viewset_classes():
        http_methods = {m.lower() for m in getattr(cls, "http_method_names", [])}
        if "delete" not in http_methods or not hasattr(cls, "destroy"):
            # Either DELETE is never wired up for this ViewSet's routes
            # (DRF's router only maps it when `destroy` exists AND it's
            # not excluded by http_method_names), or there's no
            # `destroy` to call at all — nothing to enforce here.
            continue
        if issubclass(cls, (SoftDeleteViewSetMixin, SoftDeleteDocumentViewSetMixin)):
            continue
        key = f"{cls.__module__}.{cls.__qualname__}"
        if key in _BESPOKE_SOFT_DELETE_ALLOWLIST:
            continue
        violations.append(key)

    assert not violations, (
        "These ViewSets expose a real DELETE without going through "
        "apps.common.viewsets.SoftDeleteViewSetMixin / "
        "SoftDeleteDocumentViewSetMixin, and aren't in this test's "
        "explicit, reasoned allowlist: " + ", ".join(sorted(violations))
    )
