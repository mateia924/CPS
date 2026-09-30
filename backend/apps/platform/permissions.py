"""Sprint 6.6.2 (item 3): RBAC for PlatformUser — same shape as
apps.access.permissions.HasModulePermission (an opt-in `permission_map`
read off the view), but keyed by PlatformUser.Role rather than a
Permission-code table, since platform staff only ever has three coarse
roles (see PlatformUser.Role). `super_admin` — "كل شيء" — implicitly
passes every check without needing to appear in any `permission_map`.
"""

from rest_framework.permissions import BasePermission

from .models import PlatformUser


class HasPlatformRole(BasePermission):
    """Applied to every apps.platform ViewSet/APIView alongside
    PlatformViewSet's own auth. A view without `permission_map` isn't
    gated at all here — same "opt-in, not blanket default-deny" as
    HasModulePermission — but apps.platform's own structural test
    (tests/test_platform_rbac_structural.py) fails loudly on any
    platform ViewSet that doesn't declare one, so nothing new can slip
    through ungated by accident.
    """

    def has_permission(self, request, view):
        permission_map = getattr(view, "permission_map", None)
        if not permission_map:
            return True
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.role == PlatformUser.Role.SUPER_ADMIN:
            return True
        action = getattr(view, "action", None)
        if action is None:
            action = "view" if request.method in ("GET", "HEAD", "OPTIONS") else "manage"
        allowed_roles = permission_map.get(action)
        if allowed_roles is None:
            return False
        return request.user.role in allowed_roles
