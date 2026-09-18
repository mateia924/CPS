from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import NotAuthenticated, PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import Tenant

SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


class TenantAwareJWTAuthentication(JWTAuthentication):
    """Wraps simplejwt's JWTAuthentication to enforce Tenant.status
    (sprint 2 spec section 2): an ARCHIVED tenant's users get no access
    at all (401 — indistinguishable from an invalid token); a SUSPENDED
    tenant is read-only (403 on any write, with a clear Arabic message).

    Set as DEFAULT_AUTHENTICATION_CLASSES so every existing customer
    ViewSet is covered automatically — none of them override
    authentication_classes, only permission_classes, so this applies
    globally without touching each one.
    """

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        user, validated_token = result
        tenant = getattr(user, "tenant", None)
        if tenant is not None:
            if tenant.status == Tenant.Status.ARCHIVED:
                raise NotAuthenticated(_("This tenant's account is archived."))
            if tenant.status == Tenant.Status.SUSPENDED and request.method not in SAFE_METHODS:
                raise PermissionDenied(_("This account is suspended."))
        return user, validated_token
