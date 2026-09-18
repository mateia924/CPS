from django.utils.translation import gettext_lazy as _
from rest_framework import viewsets
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
        return super().destroy(request, *args, **kwargs)


class UserViewSet(viewsets.ReadOnlyModelViewSet):
    """Tenant's users with their RBAC role and entity-access grants —
    backs the "roles & users" screen (3.14 / sprint 1 spec section 5).
    Creating users happens via /api/auth/register/ (owner) only for now;
    inviting additional users isn't in scope for this sprint.
    """

    serializer_class = UserListSerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    permission_map = {
        "list": "roles.manage",
        "retrieve": "roles.manage",
        "assign": "roles.manage",
    }

    def get_queryset(self):
        return User.objects.filter(tenant=self.request.user.tenant)

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        user = self.get_object()
        serializer = RoleAssignmentSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        if "role_ids" in serializer.validated_data:
            user.roles.set(serializer.validated_data["role_ids"])

        if "legal_entity_ids" in serializer.validated_data:
            UserEntityAccess.objects.filter(user=user).delete()
            UserEntityAccess.objects.bulk_create(
                [
                    UserEntityAccess(user=user, legal_entity=entity)
                    for entity in serializer.validated_data["legal_entity_ids"]
                ]
            )

        return Response(UserListSerializer(user).data)
