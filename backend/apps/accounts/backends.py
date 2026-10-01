from django.contrib.auth import get_user_model
from django.contrib.auth.backends import BaseBackend

from apps.tenants.models import Tenant


class TenantEmailBackend(BaseBackend):
    """Authenticate against (subdomain, email, password).

    Email is only unique *within* a tenant, so a bare email/password pair
    is not enough to identify a user — the subdomain is required for every
    tenant-facing login. The `subdomain`-less fallback below exists only
    for Django /admin/ access by platform superusers (whose email we treat
    as globally unique by convention, not by DB constraint) and must never
    be relied on for regular tenant users.
    """

    def authenticate(self, request, subdomain=None, email=None, password=None, username=None, **kwargs):
        email = email or username
        if not email or not password:
            return None

        User = get_user_model()

        if subdomain:
            try:
                tenant = Tenant.objects.get(subdomain=subdomain, is_active=True)
            except Tenant.DoesNotExist:
                return None
            try:
                user = User.objects.get(tenant=tenant, email__iexact=email)
            except User.DoesNotExist:
                return None
        else:
            # Sprint 6.6.3 (item 1): deliberately cross-tenant (Django
            # /admin/ superuser access, no subdomain) — no tenant
            # session exists at all for this lookup. Reaches "default"
            # normally (no explicit `.using(...)` needed here): this
            # branch is only ever exercised from an /admin/* request
            # (the only caller passing no `subdomain` at all), where
            # apps.tenants.middleware.AdminDatabaseRoutingMiddleware +
            # apps.tenants.routers.AdminBypassRouter already redirect
            # every query to the "platform" alias automatically —
            # sprint 6.6.3b's own structural test (tests/
            # test_platform_db_structural.py) is what keeps this
            # reasoning honest instead of silently rotting.
            candidates = list(User.objects.filter(email__iexact=email, is_superuser=True))
            if len(candidates) != 1:
                return None
            user = candidates[0]

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

    def user_can_authenticate(self, user):
        return user.is_active

    def get_user(self, user_id):
        # Sprint 6.6.3 (item 1): only ever reached via Django's own
        # session-based auth (/admin/) — apps.tenants.middleware.
        # RLSTenantMiddleware only runs for /api/* paths at all, so
        # there is no `cps.tenant_id` set on this connection for /admin/
        # requests regardless. No explicit `.using(...)` needed — same
        # reasoning as the subdomain-less branch above: Admin
        # DatabaseRoutingMiddleware/AdminBypassRouter already route
        # this to "platform" for any /admin/* request.
        User = get_user_model()
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
