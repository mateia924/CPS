from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.tenants.models import Tenant
from apps.tenants.services import apply_plan_to_tenant

from .auth import PlatformJWTAuthentication, PlatformViewSet, issue_platform_tokens
from .models import AuditLog, Plan, PlatformUser
from .serializers import (
    AuditLogSerializer,
    ChangePlanSerializer,
    ExtendTrialSerializer,
    PlanSerializer,
    PlatformLoginSerializer,
    PlatformUserSerializer,
    SuspendTenantSerializer,
    TenantAdminSerializer,
)
from .services import consume_backup_code, log_action, verify_totp


class PlatformLoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PlatformLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            user = PlatformUser.objects.get(email__iexact=data["email"])
        except PlatformUser.DoesNotExist:
            user = None

        if user is None or not user.check_password(data["password"]) or not user.is_active:
            log_action(
                actor_type=AuditLog.ActorType.PLATFORM,
                actor_id=getattr(user, "id", None),
                action="platform_user.login_failed",
                request=request,
            )
            return Response({"detail": _("Invalid email or password.")}, status=401)

        code = data.get("totp_code", "")
        if not code:
            return Response({"detail": _("A TOTP or backup code is required.")}, status=400)

        valid = verify_totp(user.totp_secret, code) or consume_backup_code(user, code)
        if not valid:
            log_action(
                actor_type=AuditLog.ActorType.PLATFORM,
                actor_id=user.id,
                action="platform_user.login_failed",
                request=request,
            )
            return Response({"detail": _("Invalid or expired code.")}, status=401)

        user.last_login = timezone.now()
        user.save(update_fields=["last_login"])
        access, refresh = issue_platform_tokens(user)
        log_action(
            actor_type=AuditLog.ActorType.PLATFORM,
            actor_id=user.id,
            action="platform_user.login",
            request=request,
        )
        return Response(
            {"access": access, "refresh": refresh, "user": PlatformUserSerializer(user).data}
        )


class PlatformMeView(APIView):
    authentication_classes = [PlatformJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(PlatformUserSerializer(request.user).data)


class PlanViewSet(PlatformViewSet):
    """Read-only for this sprint's basic screens — plan authoring/CRUD
    isn't part of "الشاشات الأساسية" (only assigning an existing plan to
    a tenant is)."""

    http_method_names = ["get", "head", "options"]
    permission_classes = [IsAuthenticated]
    serializer_class = PlanSerializer
    queryset = Plan.objects.filter(is_active=True)


class TenantAdminViewSet(PlatformViewSet):
    http_method_names = ["get", "post", "head", "options"]
    permission_classes = [IsAuthenticated]
    serializer_class = TenantAdminSerializer
    queryset = Tenant.objects.select_related("plan").order_by("-created_at")
    filter_backends = []
    search_fields = ["name", "subdomain"]

    def get_queryset(self):
        queryset = super().get_queryset()
        status_filter = self.request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        plan_filter = self.request.query_params.get("plan")
        if plan_filter:
            queryset = queryset.filter(plan__code=plan_filter)
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(name__icontains=search)
        return queryset

    @action(detail=True, methods=["post"])
    def change_plan(self, request, pk=None):
        tenant = self.get_object()
        serializer = ChangePlanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        before_plan = tenant.plan.code if tenant.plan else None
        apply_plan_to_tenant(tenant, serializer.validated_data["plan"])
        log_action(
            actor_type=AuditLog.ActorType.PLATFORM,
            actor_id=request.user.id,
            action="tenant.change_plan",
            target_type="tenant",
            target_id=tenant.id,
            tenant_id=tenant.id,
            before={"plan": before_plan},
            after={"plan": tenant.plan.code},
            request=request,
        )
        return Response(TenantAdminSerializer(tenant).data)

    @action(detail=True, methods=["post"])
    def extend_trial(self, request, pk=None):
        tenant = self.get_object()
        serializer = ExtendTrialSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        before = tenant.trial_ends_at.isoformat() if tenant.trial_ends_at else None
        tenant.trial_ends_at = serializer.validated_data["trial_ends_at"]
        tenant.save(update_fields=["trial_ends_at"])
        log_action(
            actor_type=AuditLog.ActorType.PLATFORM,
            actor_id=request.user.id,
            action="tenant.extend_trial",
            target_type="tenant",
            target_id=tenant.id,
            tenant_id=tenant.id,
            before={"trial_ends_at": before},
            after={"trial_ends_at": tenant.trial_ends_at.isoformat()},
            request=request,
        )
        return Response(TenantAdminSerializer(tenant).data)

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        tenant = self.get_object()
        serializer = SuspendTenantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        before_status = tenant.status
        tenant.status = Tenant.Status.SUSPENDED
        tenant.save(update_fields=["status"])
        log_action(
            actor_type=AuditLog.ActorType.PLATFORM,
            actor_id=request.user.id,
            action="tenant.suspend",
            target_type="tenant",
            target_id=tenant.id,
            tenant_id=tenant.id,
            before={"status": before_status, "reason": serializer.validated_data["reason"]},
            after={"status": tenant.status},
            request=request,
        )
        return Response(TenantAdminSerializer(tenant).data)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        tenant = self.get_object()
        serializer = SuspendTenantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        before_status = tenant.status
        tenant.status = Tenant.Status.ACTIVE
        tenant.save(update_fields=["status"])
        log_action(
            actor_type=AuditLog.ActorType.PLATFORM,
            actor_id=request.user.id,
            action="tenant.activate",
            target_type="tenant",
            target_id=tenant.id,
            tenant_id=tenant.id,
            before={"status": before_status, "reason": serializer.validated_data["reason"]},
            after={"status": tenant.status},
            request=request,
        )
        return Response(TenantAdminSerializer(tenant).data)


class AuditLogViewSet(PlatformViewSet):
    """Read-only, always — see AuditLog's own docstring for the DB-level
    enforcement (this ViewSet only offering list/retrieve is the
    application-level half of it)."""

    http_method_names = ["get", "head", "options"]
    permission_classes = [IsAuthenticated]
    serializer_class = AuditLogSerializer
    queryset = AuditLog.objects.all()

    def get_queryset(self):
        queryset = super().get_queryset()
        tenant_id = self.request.query_params.get("tenant_id")
        if tenant_id:
            queryset = queryset.filter(tenant_id=tenant_id)
        actor_id = self.request.query_params.get("actor_id")
        if actor_id:
            queryset = queryset.filter(actor_id=actor_id)
        actor_type = self.request.query_params.get("actor_type")
        if actor_type:
            queryset = queryset.filter(actor_type=actor_type)
        action_filter = self.request.query_params.get("action")
        if action_filter:
            queryset = queryset.filter(action=action_filter)
        date_from = self.request.query_params.get("date_from")
        if date_from:
            queryset = queryset.filter(created_at__gte=date_from)
        date_to = self.request.query_params.get("date_to")
        if date_to:
            queryset = queryset.filter(created_at__lte=date_to)
        return queryset
