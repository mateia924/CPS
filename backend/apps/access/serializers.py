from rest_framework import serializers

from apps.accounts.models import User
from apps.organization.models import LegalEntity

from .models import Permission, Role


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ("code", "description")
        read_only_fields = fields


class RoleSerializer(serializers.ModelSerializer):
    permission_codes = serializers.SlugRelatedField(
        source="permissions",
        slug_field="code",
        many=True,
        queryset=Permission.objects.all(),
        required=False,
    )

    class Meta:
        model = Role
        fields = ("id", "name", "is_system", "permission_codes", "created_at")
        read_only_fields = ("id", "is_system", "created_at")


class UserListSerializer(serializers.ModelSerializer):
    role_ids = serializers.PrimaryKeyRelatedField(source="roles", many=True, read_only=True)
    role_names = serializers.SerializerMethodField()
    legal_entity_ids = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id", "email", "first_name", "last_name", "is_active",
            "role_ids", "role_names", "legal_entity_ids",
        )
        read_only_fields = fields

    def get_role_names(self, obj):
        return list(obj.roles.values_list("name", flat=True))

    def get_legal_entity_ids(self, obj):
        return list(obj.entity_access.values_list("legal_entity_id", flat=True))


class RoleAssignmentSerializer(serializers.Serializer):
    """Replaces (not merges) a user's role and/or entity-access grants —
    whichever of the two fields is supplied. Both scoped to the acting
    user's own tenant, same pattern as InvoiceCreateSerializer.customer."""

    role_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Role.objects.none(), required=False
    )
    legal_entity_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=LegalEntity.objects.none(), required=False
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            tenant = request.user.tenant
            self.fields["role_ids"].child_relation.queryset = Role.objects.filter(tenant=tenant)
            self.fields["legal_entity_ids"].child_relation.queryset = LegalEntity.objects.filter(
                tenant=tenant
            )
