"""Sprint 6.6.2 (item 2): "الدخول بكلمة سر مؤقتة يوصل إلى شاشة «غيّر
كلمة السر» فقط حتى التغيير" — this has to be Django middleware, not a
DRF permission class, because almost every ViewSet in this project sets
its own explicit `permission_classes` list (see apps.access.
permissions.HasModulePermission and every ViewSet that uses it) rather
than relying on REST_FRAMEWORK's DEFAULT_PERMISSION_CLASSES — a global
default permission would simply never run for them. Middleware runs
before any view regardless of its own permission_classes.

`request.user` at middleware time is still Django's own session-based
AnonymousUser (JWT auth only happens later, inside DRF's dispatch) —
so this authenticates the request itself using the exact same
authentication class the views use (apps.tenants.authentication.
TenantAwareJWTAuthentication), same technique apps.platform.auth uses
for its own request inspection. This is read-only: it never replaces
DRF's own authentication, which still runs normally per-view.
"""

from django.http import JsonResponse
from django.utils.translation import gettext as _
from rest_framework.exceptions import APIException
from rest_framework_simplejwt.exceptions import TokenError

from apps.tenants.authentication import TenantAwareJWTAuthentication

# Sprint 6.6.2 (item 2): the ONLY paths a must_change_password user may
# reach — literally "شاشة «غيّر كلمة السر» فقط" — plus /me/ (read-only
# status) and /refresh/ (a dead-end without them) so the frontend can
# still tell what's going on and keep the session alive while showing
# that one screen, and /logout/ so they're never trapped.
ALLOWED_PATH_PREFIXES = (
    "/api/auth/change-password/",
    "/api/auth/me/",
    "/api/auth/refresh/",
    "/api/auth/logout/",
)


class MustChangePasswordMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.authenticator = TenantAwareJWTAuthentication()

    def __call__(self, request):
        if request.path.startswith("/api/") and not request.path.startswith(ALLOWED_PATH_PREFIXES):
            try:
                result = self.authenticator.authenticate(request)
            except (TokenError, APIException):
                result = None
            if result is not None:
                user, _token = result
                if getattr(user, "must_change_password", False):
                    return JsonResponse(
                        {"detail": str(_("يجب تغيير كلمة السر المؤقتة قبل الاستمرار."))}, status=403
                    )
        return self.get_response(request)
