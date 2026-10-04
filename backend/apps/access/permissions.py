from django.http import Http404
from rest_framework.permissions import BasePermission

from .services import user_has_permission


class HasModulePermission(BasePermission):
    """Applied to every existing business ViewSet (3.14 / sprint 1
    spec): checks the caller's role(s) grant the permission code
    required for the current action, via the view's `permission_map`
    ({action: "module.action"}).

    A ViewSet that doesn't declare `permission_map` isn't gated by this
    class at all — it's opt-in per ViewSet, not a blanket default-deny,
    so IsAuthenticated (already the DRF default) still applies on its
    own for anything that hasn't been wired into RBAC.
    """

    def has_permission(self, request, view):
        permission_map = getattr(view, "permission_map", None)
        if not permission_map:
            return True
        # Sprint 6.9.1 (item A, decision 3): `view.action` is a
        # DRF-ViewSet-only concept — a plain APIView that still declares
        # `permission_map` (keyed "view"/"manage" instead of an action
        # name) used to crash with AttributeError here, a 500 instead of
        # a 403. Safe methods read as "view", everything else as
        # "manage" — never changes behavior for an actual ViewSet,
        # which always has a real `.action`.
        action = getattr(view, "action", None)
        if action is None:
            action = "view" if request.method in ("GET", "HEAD", "OPTIONS") else "manage"
        required_code = permission_map.get(action)
        if required_code is None:
            return True
        return bool(request.user and request.user.is_authenticated) and user_has_permission(
            request.user, required_code
        )


class RequiresModuleFeature(BasePermission):
    """Sprint 7.0 (sprint-7.md §0 rule 1): a tenant whose
    `TenantFeatures` flag for this module is off gets a genuine 404,
    not 403 — the whole module doesn't exist for them, same as it
    would if the URL itself weren't registered, not merely "access
    denied" to something they can at least see exists. First real
    enforcement of TenantFeatures.* as an actual gate — until now every
    flag (inventory/purchasing/hr/treasury/assets) was read only by
    billing (apps.tenants.services.apply_plan_to_tenant) and the
    frontend menu, never by the API itself.

    Opt-in via `view.module_feature = "inventory"` (a TenantFeatures
    field name) — a ViewSet/APIView that doesn't set it isn't gated by
    this class at all, same opt-in shape as HasModulePermission's own
    `permission_map`. Raising Http404 directly (rather than returning
    False, which DRF would turn into 403) is what gets the 404 — DRF's
    exception handler converts Http404 to a 404 response the same way
    Django itself does.
    """

    def has_permission(self, request, view):
        feature_name = getattr(view, "module_feature", None)
        if feature_name is None:
            return True
        if not (request.user and request.user.is_authenticated):
            # Let authentication (or whatever runs instead of this
            # permission) produce the 401/403 it normally would —
            # never mask "not logged in" as "module doesn't exist".
            return True
        tenant = getattr(request.user, "tenant", None)
        features = getattr(tenant, "features", None) if tenant else None
        if features is None or getattr(features, feature_name, True):
            return True
        raise Http404()
