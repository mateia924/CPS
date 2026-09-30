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

import json

from django.db import connections, transaction
from rest_framework.exceptions import APIException
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import UntypedToken

from apps.common.rls import clear_local_tenant_id, set_local_tenant_id
from apps.tenants.authentication import TenantAwareJWTAuthentication
from apps.tenants.routers import clear_admin_request, mark_admin_request

EXEMPT_PATHS = ("/api/health/",)

# Sprint 6.6.3 (item 1): the one endpoint whose token travels in the
# POST body instead of the Authorization header — simplejwt's own
# stock TokenRefreshView, whose TokenRefreshSerializer.validate() does
# its own SELECT on accounts_user (the same RLS-protected query every
# other fix in this file works around) using the user_id claim off
# the refresh token itself.
REFRESH_TOKEN_PATH = "/api/auth/refresh/"


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
    """`tenant_id` is read directly off the ACCESS TOKEN'S OWN claims
    (apps.accounts.views._tokens_for_user sets `refresh["tenant_id"]`,
    and simplejwt's RefreshToken.access_token copies every custom
    claim over) — deliberately NOT via a full TenantAwareJWTAuthentica
    tion.authenticate() call, which was this middleware's first
    version and broke live logins the hard way: that call's own
    get_user() is itself a SELECT on accounts_user (RLS-protected), and
    at the point this middleware runs, `cps.tenant_id` isn't set yet —
    that's exactly what it's trying to determine. Decoding the token
    (get_validated_token(), pure cryptographic/claims validation, no DB
    query at all) and reading `tenant_id` straight from its payload
    sidesteps the chicken-and-egg entirely. The real, full
    authentication (including the User SELECT, now correctly scoped)
    still happens normally afterward, inside the view's own dispatch().
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.authenticator = TenantAwareJWTAuthentication()

    def __call__(self, request):
        if not request.path.startswith("/api/") or request.path in EXEMPT_PATHS:
            return self.get_response(request)

        with transaction.atomic(using="default"):
            tenant_id = None
            header = self.authenticator.get_header(request)
            if header is not None:
                raw_token = self.authenticator.get_raw_token(header)
                if raw_token is not None:
                    try:
                        validated_token = self.authenticator.get_validated_token(raw_token)
                    except (TokenError, APIException):
                        validated_token = None
                    if validated_token is not None:
                        tenant_id = validated_token.get("tenant_id")

            if tenant_id is None and request.path == REFRESH_TOKEN_PATH:
                try:
                    raw_refresh = json.loads(request.body or b"{}").get("refresh")
                except (ValueError, UnicodeDecodeError):
                    raw_refresh = None
                if raw_refresh:
                    try:
                        tenant_id = UntypedToken(raw_refresh).get("tenant_id")
                    except TokenError:
                        tenant_id = None

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
