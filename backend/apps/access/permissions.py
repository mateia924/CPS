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
        required_code = permission_map.get(view.action)
        if required_code is None:
            return True
        return bool(request.user and request.user.is_authenticated) and user_has_permission(
            request.user, required_code
        )
