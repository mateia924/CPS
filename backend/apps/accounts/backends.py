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
            # session exists at all for this lookup, so it uses the
            # "platform" DB alias (config.settings.DATABASES, the
            # original unrestricted role) rather than "default", same
            # as every other pre-auth/cross-tenant caller.
            candidates = list(User.objects.using("platform").filter(email__iexact=email, is_superuser=True))
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
        # requests regardless. "platform" alias, same as the
        # subdomain-less superuser lookup above this reloads a session
        # for.
        User = get_user_model()
        try:
            return User.objects.using("platform").get(pk=user_id)
        except User.DoesNotExist:
            return None
