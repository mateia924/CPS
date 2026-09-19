from django.db import transaction
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.organization.models import LegalEntity

from .models import Party, PartyRole
from .services import generate_party_code, link_employee_cost_center


class PartyRoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = PartyRole
        fields = ("id", "role", "is_active", "details", "legal_entity", "created_at")
        read_only_fields = ("id", "created_at")


class PartyRoleInputSerializer(serializers.Serializer):
    """Shared shape for the role added at Party creation and for the
    standalone add_role action."""

    role = serializers.ChoiceField(choices=PartyRole.Role.choices)
    details = serializers.JSONField(required=False, default=dict)
    legal_entity = serializers.PrimaryKeyRelatedField(
        queryset=LegalEntity.objects.none(), required=False, allow_null=True
    )
    # 3.3 section 4: "معطّل للموظفين" — opt-in, off by default, unlike
    # the vehicle asset case which defaults on.
    create_linked_cost_center = serializers.BooleanField(required=False, default=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            self.fields["legal_entity"].queryset = LegalEntity.objects.filter(
                tenant=request.user.tenant
            )

    def validate(self, attrs):
        if attrs["role"] == PartyRole.Role.AFFILIATE and not attrs.get("legal_entity"):
            raise serializers.ValidationError(
                {"legal_entity": [_("An affiliate role requires a matching legal entity.")]}
            )
        return attrs


class PartySerializer(serializers.ModelSerializer):
    roles = PartyRoleSerializer(many=True, read_only=True)
    # Write-only: the first role a new party is created with — 3.3's
    # frontend spec requires "دور واحد على الأقل" at creation time.
    role = serializers.ChoiceField(choices=PartyRole.Role.choices, write_only=True)
    role_details = serializers.JSONField(required=False, default=dict, write_only=True)
    role_legal_entity = serializers.PrimaryKeyRelatedField(
        queryset=LegalEntity.objects.none(), required=False, allow_null=True, write_only=True
    )
    role_create_linked_cost_center = serializers.BooleanField(
        required=False, default=False, write_only=True
    )

    class Meta:
        model = Party
        fields = (
            "id", "code", "name", "name_en", "party_type", "tax_number",
            "national_id_or_cr", "phone", "email", "address", "country_code",
            "default_currency", "notes", "is_active", "roles", "role",
            "role_details", "role_legal_entity", "role_create_linked_cost_center", "created_at",
        )
        read_only_fields = ("id", "code", "roles", "created_at")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            self.fields["role_legal_entity"].queryset = LegalEntity.objects.filter(
                tenant=request.user.tenant
            )
        # `role`/`role_details`/`role_legal_entity`/... only apply at
        # creation — editing an existing party's basic fields never
        # touches its roles (use the add_role action for that).
        if self.instance is not None:
            for field_name in (
                "role", "role_details", "role_legal_entity", "role_create_linked_cost_center"
            ):
                self.fields.pop(field_name, None)

    def validate(self, attrs):
        if self.instance is None and attrs.get("role") == PartyRole.Role.AFFILIATE and not attrs.get(
            "role_legal_entity"
        ):
            raise serializers.ValidationError(
                {"role_legal_entity": [_("An affiliate role requires a matching legal entity.")]}
            )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        role = validated_data.pop("role")
        role_details = validated_data.pop("role_details", {})
        role_legal_entity = validated_data.pop("role_legal_entity", None)
        create_linked_cost_center = validated_data.pop("role_create_linked_cost_center", False)
        # `tenant` arrives here via TenantScopedViewSet.perform_create's
        # `serializer.save(tenant=...)` kwarg, merged into validated_data
        # by DRF before create() is called — never trust request context
        # for it directly, same as every other tenant-scoped serializer.
        tenant = validated_data["tenant"]
        party = Party.objects.create(code=generate_party_code(tenant), **validated_data)
        PartyRole.objects.create(
            party=party, role=role, details=role_details, legal_entity=role_legal_entity
        )
        if role == PartyRole.Role.EMPLOYEE and create_linked_cost_center:
            link_employee_cost_center(party)
        return party
