from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from apps.accounts.models import User
from apps.organization.models import LegalEntity
from apps.organization.services import default_branch_for_tenant, is_simplified_mode

from .models import Permission, Role, UserEntityAccess


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


class CreateUserSerializer(serializers.Serializer):
    """Adds a staff user to the caller's own tenant — see
    apps/access/views.py: UserViewSet.create for the max_users plan-limit
    check (sprint 2). Never creates an Owner; the tenant admin assigns a
    role afterward via UserViewSet.assign, same as any other user.

    Sprint 5.0 (post-UAT-4 fix): entity access is granted right here at
    creation time instead of requiring a separate `/assign/` call
    afterward — the recurring "0 accessible entities" gotcha hit during
    UAT 4 (a brand-new non-Owner user could see nothing until someone
    remembered the second call). Simplified-mode tenants (single
    company+branch) need no input at all: the one branch is granted
    automatically. Multi-entity tenants get an optional advanced
    `legal_entity_ids` field; omitting it grants every entity in the
    tenant (the stated default), matching "كل الكيانات" in the spec.
    """

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, validators=[validate_password])
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    legal_entity_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=LegalEntity.objects.none(), required=False
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            self.fields["legal_entity_ids"].child_relation.queryset = LegalEntity.objects.filter(
                tenant=request.user.tenant
            )

    def validate_email(self, value):
        tenant = self.context["request"].user.tenant
        if User.objects.filter(tenant=tenant, email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists in your company.")
        return value

    def create(self, validated_data):
        tenant = self.context["request"].user.tenant
        user = User.objects.create_user(
            tenant=tenant,
            email=validated_data["email"],
            password=validated_data["password"],
            first_name=validated_data.get("first_name", ""),
            last_name=validated_data.get("last_name", ""),
            role=User.Role.STAFF,
            is_staff=False,
        )

        if is_simplified_mode(tenant):
            branch = default_branch_for_tenant(tenant)
            if branch is not None:
                UserEntityAccess.objects.create(user=user, legal_entity=branch)
        else:
            entities = validated_data.get("legal_entity_ids") or list(
                LegalEntity.objects.filter(tenant=tenant, is_active=True)
            )
            UserEntityAccess.objects.bulk_create(
                [UserEntityAccess(user=user, legal_entity=entity) for entity in entities]
            )

        return user


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
