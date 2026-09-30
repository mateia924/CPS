"""Sprint 6.6.3 (item 1): sets the Postgres session variable every
`tenant_isolation` RLS policy reads (apps.tenants.services.
configure_database_roles_and_rls). Same reasoning as apps.accounts.
middleware.MustChangePasswordMiddleware for why this is plain Django
middleware authenticating the request itself, not a DRF permission
class: it needs to run before the view, and DRF authentication only
happens inside the view's own dispatch().

Deliberately does NOT rely on DATABASES["default"]["ATOMIC_REQUESTS"]:
Django only wraps the *resolved view callable itself* in that atomic
block (docs: "Django wraps... around each view function it calls" —
middleware runs outside it), which is too late — `SET LOCAL` with no
transaction open yet is an implicit, immediately-committed one-
statement transaction under autocommit, so its effect would vanish
before the view's own (separately-wrapped) transaction even starts.
This middleware opens its OWN `transaction.atomic()` around the ENTIRE
rest of the chain (every later middleware + the view), so `SET LOCAL`
issued right at the start stays in effect for everything that follows,
in the same transaction, for the whole request.

Skips `/api/health/` entirely — a plain liveness probe with no DB
query of its own; wrapping it would force open a real DB connection
just to answer "is the process up", which defeats its purpose as a
liveness check independent of DB health.
"""

from django.db import connections, transaction
from rest_framework.exceptions import APIException
from rest_framework_simplejwt.exceptions import TokenError

from apps.common.rls import clear_local_tenant_id, set_local_tenant_id
from apps.tenants.authentication import TenantAwareJWTAuthentication
from apps.tenants.routers import clear_admin_request, mark_admin_request

EXEMPT_PATHS = ("/api/health/",)


class AdminDatabaseRoutingMiddleware:
    """Sprint 6.6.3 (item 1): see apps.tenants.routers.AdminBypassRouter's
    own docstring — /admin/ has no JWT/tenant-request concept at all
    for RLSTenantMiddleware below to have set `cps.tenant_id` from, and
    is inherently cross-tenant by nature anyway."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith("/admin/"):
            return self.get_response(request)
        mark_admin_request()
        try:
            return self.get_response(request)
        finally:
            clear_admin_request()


class RLSTenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.authenticator = TenantAwareJWTAuthentication()

    def __call__(self, request):
        if not request.path.startswith("/api/") or request.path in EXEMPT_PATHS:
            return self.get_response(request)

        with transaction.atomic(using="default"):
            tenant_id = None
            try:
                result = self.authenticator.authenticate(request)
            except (TokenError, APIException):
                result = None
            if result is not None:
                user, _token = result
                tenant_id = getattr(user, "tenant_id", None)

            with connections["default"].cursor() as cursor:
                # Sprint 6.6.3: the `true` (missing_ok) form of
                # current_setting() is what every tenant_isolation
                # policy relies on — a platform-staff request (no
                # tenant_id at all, apps.platform.auth.
                # PlatformJWTAuthentication signs with a different key
                # TenantAwareJWTAuthentication can never verify) or a
                # request with no valid tenant token simply never
                # matches any row on the "default" connection, rather
                # than erroring. Platform code reaches tenant data
                # deliberately, through the separate "platform" DB
                # alias (config.settings.DATABASES), which has no RLS
                # policy applied to it at all — its role is the
                # original, unrestricted one.
                if tenant_id:
                    set_local_tenant_id(cursor, tenant_id)
                else:
                    clear_local_tenant_id(cursor)

            response = self.get_response(request)
        return response
