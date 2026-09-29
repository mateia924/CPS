from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.access.models import Role
from apps.common.ratelimit import check_auth_ratelimit
from apps.organization.services import (
    default_legal_entity_id_for_user,
    get_accessible_entity_ids,
    is_simplified_mode,
)
from apps.tenants.models import TenantFeatures

from .serializers import RegisterSerializer, TenantLoginSerializer, TenantSerializer, UserSerializer


def _tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    refresh["tenant_id"] = str(user.tenant_id)
    refresh["tenant_subdomain"] = user.tenant.subdomain
    refresh["role"] = user.role
    return {"refresh": str(refresh), "access": str(refresh.access_token)}


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        limited = check_auth_ratelimit(request, "auth-register", request.data.get("email"))
        if limited:
            return limited
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        user = result["user"]
        return Response(
            {
                "tenant": TenantSerializer(result["tenant"]).data,
                "user": UserSerializer(user).data,
                **_tokens_for_user(user),
            },
            status=201,
        )


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        limited = check_auth_ratelimit(request, "auth-login", request.data.get("email"))
        if limited:
            return limited
        serializer = TenantLoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        # Drives the platform tenant list's "آخر نشاط" column (sprint 2).
        user.last_login = timezone.now()
        user.save(update_fields=["last_login"])
        return Response(
            {
                "tenant": TenantSerializer(user.tenant).data,
                "user": UserSerializer(user).data,
                **_tokens_for_user(user),
            }
        )


class LogoutView(APIView):
    """Sprint 6 (block 6.0, item 6 — CFO_REVIEW_1 §7 Q18): blacklists
    the refresh token so it can never be used again, closing the gap a
    leaked/still-valid-after-"logout" refresh token left open (5.7's
    verification answer documented this as a real, then-unfixed gap).
    The access token itself is short-lived (30 min default) and is
    simply discarded client-side, same as before."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh = request.data.get("refresh")
        if not refresh:
            return Response({"detail": [str(_("A refresh token is required."))]}, status=400)
        try:
            token = RefreshToken(refresh)
            token.blacklist()
        except TokenError:
            # Already expired/blacklisted/malformed — logging out is
            # still a success from the caller's point of view.
            pass
        return Response(status=204)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        tenant = user.tenant

        permission_codes = sorted(
            set(
                Role.objects.filter(users=user)
                .values_list("permissions__code", flat=True)
                .exclude(permissions__code__isnull=True)
            )
        )

        try:
            features = tenant.features
        except TenantFeatures.DoesNotExist:
            # Sprint 4.8: GET must never write — a real tenant always
            # gets its row at registration (apply_plan_to_tenant) or via
            # a backfill migration for pre-existing ones; this branch is
            # only a defensive fallback (e.g. a tenant created directly
            # by a factory in tests), so it builds an unsaved instance
            # with the model's own defaults rather than persisting one.
            features = TenantFeatures(tenant=tenant)

        accessible_ids = get_accessible_entity_ids(user)
        default_id = default_legal_entity_id_for_user(user, accessible_ids)

        return Response(
            {
                "tenant": TenantSerializer(tenant).data,
                "user": UserSerializer(user).data,
                "roles": list(user.roles.values_list("name", flat=True)),
                "permissions": permission_codes,
                "legal_entity_ids": sorted(str(eid) for eid in accessible_ids),
                "default_legal_entity_id": str(default_id) if default_id else None,
                "features": {
                    "organization": features.organization,
                    "cost_centers": features.cost_centers,
                    "inventory": features.inventory,
                    "purchasing": features.purchasing,
                    "hr": features.hr,
                    "treasury": features.treasury,
                    "assets": features.assets,
                },
                "simplified_mode": is_simplified_mode(tenant),
            }
        )

    def patch(self, request):
        # Sprint 6.8 (decision 17): "ملف المستخدم" — self-service, one
        # field only (notify_approvals_email); no admin-editable-other-
        # user path exists yet (UserViewSet is still read-only + create),
        # so this stays a narrow PATCH on the caller's own row rather
        # than a general user-update endpoint.
        if "notify_approvals_email" in request.data:
            request.user.notify_approvals_email = bool(request.data["notify_approvals_email"])
            request.user.save(update_fields=["notify_approvals_email"])
        return self.get(request)
