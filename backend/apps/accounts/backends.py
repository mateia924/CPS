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
        User = get_user_model()
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
