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
from apps.platform.models import AuditLog
from apps.platform.services import log_action
from apps.tenants.models import TenantFeatures

from .serializers import (
    ChangePasswordSerializer,
    RegisterSerializer,
    TenantLoginSerializer,
    TenantSerializer,
    UserSerializer,
)
from .services import (
    consume_backup_code,
    generate_backup_codes,
    generate_totp_secret,
    invalidate_all_sessions,
    record_session,
    totp_provisioning_uri,
    totp_qr_data_uri,
    user_requires_2fa_setup,
    verify_totp,
)


def _tokens_for_user(user, request=None):
    refresh = RefreshToken.for_user(user)
    refresh["tenant_id"] = str(user.tenant_id)
    refresh["tenant_subdomain"] = user.tenant.subdomain
    refresh["role"] = user.role
    record_session(user, refresh, request)
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
                **_tokens_for_user(user, request),
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

        # Sprint 6.6.2 (item 1): the password is already verified at
        # this point (TenantLoginSerializer.validate) and its own
        # "tenant_user.login" audit line already written — 2FA is a
        # second, separate gate on top, logged distinctly on failure so
        # the audit trail can tell "wrong password" apart from "right
        # password, missing/wrong code". Only `totp_confirmed` ever
        # requires a code; `require_2fa_for_roles` alone (not yet
        # enrolled) never blocks login, only flags requires_2fa_setup
        # below so the frontend forces the enrollment screen next.
        if user.totp_confirmed:
            code = request.data.get("totp_code", "")
            if not code:
                return Response({"detail": _("A TOTP or backup code is required.")}, status=403)
            if not (verify_totp(user.totp_secret, code) or consume_backup_code(user, code)):
                log_action(
                    actor_type=AuditLog.ActorType.TENANT_USER,
                    actor_id=user.id,
                    action="tenant_user.login_2fa_failed",
                    tenant_id=user.tenant_id,
                    request=request,
                )
                return Response({"detail": _("Invalid or expired code.")}, status=403)

        # Drives the platform tenant list's "آخر نشاط" column (sprint 2).
        user.last_login = timezone.now()
        user.save(update_fields=["last_login"])
        return Response(
            {
                "tenant": TenantSerializer(user.tenant).data,
                "user": UserSerializer(user).data,
                "must_change_password": user.must_change_password,
                "requires_2fa_setup": user_requires_2fa_setup(user),
                **_tokens_for_user(user, request),
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
                "requires_2fa_setup": user_requires_2fa_setup(user),
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


class ChangePasswordView(APIView):
    """Sprint 6.6.2 (item 2): the one screen a must_change_password
    user can reach (apps.accounts.middleware.MustChangePasswordMiddle
    ware) — also the ordinary self-service "ملفي الشخصي" path any user
    can use any time. Either way, changing the password ends every
    other session ("انتهاء refresh token عند تغيير كلمة السر") —
    the caller's own current refresh token is blacklisted too, so the
    frontend must treat this like a logout and send the user back to
    /login/ with the new password."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = request.user
        user.set_password(serializer.validated_data["new_password"])
        user.must_change_password = False
        user.save(update_fields=["password", "must_change_password"])
        invalidate_all_sessions(user)
        log_action(
            actor_type=AuditLog.ActorType.TENANT_USER,
            actor_id=user.id,
            action="tenant_user.change_password",
            target_type="accounts.User",
            target_id=user.id,
            tenant_id=user.tenant_id,
            request=request,
        )
        return Response(status=204)


class TwoFactorSetupView(APIView):
    """Sprint 6.6.2 (item 1): step 1 of enrollment — generates a fresh
    secret (saved but NOT yet `totp_confirmed`, so it grants no access
    on its own) and returns it as a QR code + the raw secret for manual
    entry. Calling this again before confirming simply replaces the
    pending secret — no harm, nothing was trusted yet."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        secret = generate_totp_secret()
        user.totp_secret = secret
        user.totp_confirmed = False
        user.save(update_fields=["totp_secret", "totp_confirmed"])
        uri = totp_provisioning_uri(user, secret)
        return Response({"secret": secret, "qr_code": totp_qr_data_uri(uri)})


class TwoFactorConfirmView(APIView):
    """Step 2: proves the operator actually enrolled the secret in a
    real authenticator app before it becomes the account's 2FA gate.
    Backup codes are only ever generated here, once, and shown back in
    the plaintext response body — never retrievable again afterward."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        code = request.data.get("code", "")
        if not user.totp_secret or not verify_totp(user.totp_secret, code):
            return Response({"detail": _("Invalid or expired code.")}, status=400)
        user.totp_confirmed = True
        user.save(update_fields=["totp_confirmed"])
        codes = generate_backup_codes(user)
        log_action(
            actor_type=AuditLog.ActorType.TENANT_USER,
            actor_id=user.id,
            action="tenant_user.2fa_enabled",
            target_type="accounts.User",
            target_id=user.id,
            tenant_id=user.tenant_id,
            request=request,
        )
        return Response({"backup_codes": codes})


class TwoFactorDisableView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if not user.check_password(request.data.get("password", "")):
            return Response({"detail": _("Current password is incorrect.")}, status=400)
        user.totp_secret = ""
        user.totp_confirmed = False
        user.save(update_fields=["totp_secret", "totp_confirmed"])
        user.backup_codes.all().delete()
        log_action(
            actor_type=AuditLog.ActorType.TENANT_USER,
            actor_id=user.id,
            action="tenant_user.2fa_disabled",
            target_type="accounts.User",
            target_id=user.id,
            tenant_id=user.tenant_id,
            request=request,
        )
        return Response(status=204)


class SessionListView(APIView):
    """Sprint 6.6.2 (item 4): "قائمة الجلسات النشطة" — see
    apps.accounts.models.UserSession's docstring for why this is a
    separate, display-only table rather than reading OutstandingToken
    directly."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import UserSession

        sessions = UserSession.objects.filter(
            user=request.user, revoked_at__isnull=True, expires_at__gte=timezone.now()
        )
        return Response(
            [
                {
                    "id": str(s.id),
                    "ip_address": s.ip_address,
                    "user_agent": s.user_agent,
                    "created_at": s.created_at,
                }
                for s in sessions
            ]
        )


class LogoutAllView(APIView):
    """Sprint 6.6.2 (item 4): "تسجيل الخروج من كل الأجهزة"."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        invalidate_all_sessions(request.user)
        log_action(
            actor_type=AuditLog.ActorType.TENANT_USER,
            actor_id=request.user.id,
            action="tenant_user.logout_all",
            target_type="accounts.User",
            target_id=request.user.id,
            tenant_id=request.user.tenant_id,
            request=request,
        )
        return Response(status=204)
