from django.db.models.deletion import Collector, ProtectedError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import filters, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.models import User
from apps.accounts.services import invalidate_all_sessions
from apps.common.viewsets import TenantScopedViewSet, log_master_data_change
from apps.platform.models import AuditLog
from apps.platform.services import log_action
from apps.tenants.services import TenantLimitExceeded, check_user_limit

from .models import Permission, Role, UserEntityAccess
from .permissions import HasModulePermission
from .serializers import (
    CreateUserSerializer,
    PermissionSerializer,
    ResetPasswordSerializer,
    RoleAssignmentSerializer,
    RoleSerializer,
    UserListSerializer,
)
from .services import active_owner_count, user_is_owner


class PermissionViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only global catalog — used to build the role-editing UI."""

    serializer_class = PermissionSerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = Permission.objects.all()
    permission_map = {"list": "roles.manage", "retrieve": "roles.manage"}


class RoleViewSet(TenantScopedViewSet):
    serializer_class = RoleSerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = Role.objects.all()
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name"]
    ordering_fields = ["name", "created_at"]
    permission_map = {
        "list": "roles.manage",
        "retrieve": "roles.manage",
        "create": "roles.manage",
        "update": "roles.manage",
        "partial_update": "roles.manage",
        "destroy": "roles.manage",
    }

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)

    def perform_create(self, serializer):
        # Roles created through the API are never system roles — only
        # the four seeded at registration are (see access/services.py).
        serializer.save(tenant=self.request.user.tenant, is_system=False)

    def destroy(self, request, *args, **kwargs):
        # Sprint 6.6.5 (unified delete rule, "لا DELETE فعلي في أي
        # مكان"): this used to fall through to super().destroy() (a
        # real SQL DELETE) once past the system-role/M2M-users guards
        # below — soft-deleting instead now, same as every other
        # master-data ViewSet. Role.users is a plain M2M (no on_delete=
        # PROTECT to lean on — that's FK-only), so "in use" still needs
        # this explicit check; a role referenced by ApprovalRule.
        # required_role (a real PROTECT FK) is caught by the Collector
        # the same way SoftDeleteViewSetMixin does it for every other
        # model, instead of the crash this would previously raise.
        role = self.get_object()
        if role.is_system:
            return Response({"detail": _("System roles cannot be deleted.")}, status=400)
        if role.users.exists():
            return Response(
                {"detail": _("This role is assigned to at least one user and cannot be deleted.")},
                status=409,
            )
        collector = Collector(using=role._state.db)
        try:
            collector.collect([role])
        except ProtectedError:
            return Response(
                {"detail": _("This role is referenced elsewhere and cannot be deleted.")},
                status=status.HTTP_409_CONFLICT,
            )
        role.deleted_at = timezone.now()
        role.deleted_by = request.user
        role.save(update_fields=["deleted_at", "deleted_by"])
        log_master_data_change(request, role, "deleted")
        return Response(status=status.HTTP_204_NO_CONTENT)


class UserViewSet(mixins.CreateModelMixin, viewsets.ReadOnlyModelViewSet):
    """Tenant's users with their RBAC role and entity-access grants —
    backs the "roles & users" screen (3.14 / sprint 1 spec section 5).

    Sprint 2 (3.14): `create` adds a Staff user to the caller's own
    tenant, enforcing the plan's max_users limit (402 on exceed) — this
    is the minimal "add user" endpoint needed to make that limit
    testable at all; previously (sprint 1) users only ever came from
    /api/auth/register/ (the Owner). Logged in the Decision Log.
    """

    permission_classes = [IsAuthenticated, HasModulePermission]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["email", "first_name", "last_name"]
    ordering_fields = ["email", "date_joined"]
    permission_map = {
        "list": "roles.manage",
        "retrieve": "roles.manage",
        "create": "roles.manage",
        "assign": "roles.manage",
        "deactivate": "roles.manage",
        "activate": "roles.manage",
        "reset_password": "roles.manage",
    }

    def get_serializer_class(self):
        if self.action == "create":
            return CreateUserSerializer
        return UserListSerializer

    def get_queryset(self):
        queryset = User.objects.filter(tenant=self.request.user.tenant)
        if self.action == "list" and self.request.query_params.get("show_inactive") != "true":
            queryset = queryset.filter(is_active=True)
        return queryset

    def create(self, request, *args, **kwargs):
        try:
            check_user_limit(request.user.tenant)
        except TenantLimitExceeded as exc:
            return Response({"detail": exc.message}, status=402)

        serializer = CreateUserSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        log_action(
            actor_type=AuditLog.ActorType.TENANT_USER,
            actor_id=request.user.id,
            action="tenant_user.create",
            target_type="accounts.User",
            target_id=user.id,
            tenant_id=request.user.tenant_id,
            after={"email": user.email},
            request=request,
        )
        return Response(UserListSerializer(user).data, status=201)

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        user = self.get_object()
        serializer = RoleAssignmentSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        if "role_ids" in serializer.validated_data:
            new_roles = serializer.validated_data["role_ids"]
            still_owner = any(r.name == "Owner" and r.is_system for r in new_roles)
            # sprint 1.5 rule 3: a tenant must always keep >= 1 active
            # Owner — block removing the role from the last one.
            if not still_owner and user_is_owner(user) and user.is_active:
                if active_owner_count(user.tenant, exclude_user_id=user.id) == 0:
                    return Response(
                        {"detail": _("At least one active Owner is required per tenant.")},
                        status=400,
                    )
            user.roles.set(new_roles)

        if "legal_entity_ids" in serializer.validated_data:
            UserEntityAccess.objects.filter(user=user).delete()
            UserEntityAccess.objects.bulk_create(
                [
                    UserEntityAccess(user=user, legal_entity=entity)
                    for entity in serializer.validated_data["legal_entity_ids"]
                ]
            )

        log_action(
            actor_type=AuditLog.ActorType.TENANT_USER,
            actor_id=request.user.id,
            action="tenant_user.role_assign",
            target_type="accounts.User",
            target_id=user.id,
            tenant_id=request.user.tenant_id,
            after={
                "role_ids": [str(r.id) for r in serializer.validated_data.get("role_ids", [])],
                "legal_entity_ids": [
                    str(e.id) for e in serializer.validated_data.get("legal_entity_ids", [])
                ],
            },
            request=request,
        )
        return Response(UserListSerializer(user).data)

    @action(detail=True, methods=["post"])
    def reset_password(self, request, pk=None):
        """Sprint 6.6.2 (item 2): "إعادة التعيين من «تعديل»" — sets a
        temporary password and forces the change-password screen on
        the target's next login; also ends every session they're
        currently in, same as a self-service password change."""
        user = self.get_object()
        serializer = ResetPasswordSerializer(data=request.data, context={"user": user})
        serializer.is_valid(raise_exception=True)
        user.set_password(serializer.validated_data["new_password"])
        user.must_change_password = True
        user.save(update_fields=["password", "must_change_password"])
        invalidate_all_sessions(user)
        log_action(
            actor_type=AuditLog.ActorType.TENANT_USER,
            actor_id=request.user.id,
            action="tenant_user.reset_password",
            target_type="accounts.User",
            target_id=user.id,
            tenant_id=request.user.tenant_id,
            request=request,
        )
        return Response(UserListSerializer(user).data)

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        user = self.get_object()
        if user_is_owner(user) and active_owner_count(user.tenant, exclude_user_id=user.id) == 0:
            return Response(
                {"detail": _("At least one active Owner is required per tenant.")}, status=400
            )
        user.is_active = False
        user.save(update_fields=["is_active"])
        # Sprint 6.6.2 (item 4): "تعطيل المستخدم (إبطال كل التوكنات)" —
        # simplejwt's own access-token auth already re-checks is_active
        # per request, but TokenRefreshView never does, so a deactivated
        # user could otherwise keep minting fresh access tokens forever
        # from a refresh token issued before deactivation.
        invalidate_all_sessions(user)
        log_action(
            actor_type=AuditLog.ActorType.TENANT_USER,
            actor_id=request.user.id,
            action="tenant_user.deactivate",
            target_type="accounts.User",
            target_id=user.id,
            tenant_id=request.user.tenant_id,
            request=request,
        )
        return Response(UserListSerializer(user).data)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        user = self.get_object()
        user.is_active = True
        user.save(update_fields=["is_active"])
        log_action(
            actor_type=AuditLog.ActorType.TENANT_USER,
            actor_id=request.user.id,
            action="tenant_user.activate",
            target_type="accounts.User",
            target_id=user.id,
            tenant_id=request.user.tenant_id,
            request=request,
        )
        return Response(UserListSerializer(user).data)
