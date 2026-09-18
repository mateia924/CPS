from django.utils.translation import gettext_lazy as _
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.models import User
from apps.common.viewsets import TenantScopedViewSet

from .models import Permission, Role, UserEntityAccess
from .permissions import HasModulePermission
from .serializers import (
    PermissionSerializer,
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

    def perform_create(self, serializer):
        # Roles created through the API are never system roles — only
        # the four seeded at registration are (see access/services.py).
        serializer.save(tenant=self.request.user.tenant, is_system=False)

    def destroy(self, request, *args, **kwargs):
        role = self.get_object()
        if role.is_system:
            return Response({"detail": _("System roles cannot be deleted.")}, status=400)
        # Role.users is a plain M2M (no on_delete=PROTECT to lean on —
        # that's FK-only), so "in use" needs an explicit check here
        # rather than catching ProtectedError like SoftDeleteViewSetMixin
        # does for FK-protected models.
        if role.users.exists():
            return Response(
                {"detail": _("This role is assigned to at least one user and cannot be deleted.")},
                status=409,
            )
        return super().destroy(request, *args, **kwargs)


class UserViewSet(viewsets.ReadOnlyModelViewSet):
    """Tenant's users with their RBAC role and entity-access grants —
    backs the "roles & users" screen (3.14 / sprint 1 spec section 5).
    Creating users happens via /api/auth/register/ (owner) only for now;
    inviting additional users isn't in scope for this sprint.
    """

    serializer_class = UserListSerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["email", "first_name", "last_name"]
    ordering_fields = ["email", "date_joined"]
    permission_map = {
        "list": "roles.manage",
        "retrieve": "roles.manage",
        "assign": "roles.manage",
        "deactivate": "roles.manage",
        "activate": "roles.manage",
    }

    def get_queryset(self):
        queryset = User.objects.filter(tenant=self.request.user.tenant)
        if self.action == "list" and self.request.query_params.get("show_inactive") != "true":
            queryset = queryset.filter(is_active=True)
        return queryset

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
        return Response(UserListSerializer(user).data)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        user = self.get_object()
        user.is_active = True
        user.save(update_fields=["is_active"])
        return Response(UserListSerializer(user).data)
