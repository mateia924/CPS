from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.access.services import seed_default_roles
from apps.accounting.services import seed_chart_of_accounts
from apps.organization.services import create_default_legal_entities
from apps.tenants.models import Tenant, TenantFeatures

from .models import User


class TenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = ("id", "name", "subdomain", "created_at")
        read_only_fields = fields


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "email", "first_name", "last_name", "role", "date_joined")
        read_only_fields = fields


class RegisterSerializer(serializers.Serializer):
    company_name = serializers.CharField(max_length=255)
    subdomain = serializers.SlugField(max_length=63)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, validators=[validate_password])
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")

    def validate_subdomain(self, value):
        value = value.lower()
        if Tenant.objects.filter(subdomain=value).exists():
            raise serializers.ValidationError(_("This subdomain is already taken."))
        return value

    def create(self, validated_data):
        with transaction.atomic():
            tenant = Tenant.objects.create(
                name=validated_data["company_name"],
                subdomain=validated_data["subdomain"],
            )
            user = User.objects.create_user(
                tenant=tenant,
                email=validated_data["email"],
                password=validated_data["password"],
                first_name=validated_data.get("first_name", ""),
                last_name=validated_data.get("last_name", ""),
                role=User.Role.OWNER,
                is_staff=True,
            )
            seed_chart_of_accounts(tenant)

            # Sprint 1 (docs/SYSTEM_ANALYSIS.md 3.1, 3.13, 3.14): default
            # legal structure, system roles, and feature flags for every
            # new tenant. The registering user always gets the Owner
            # role, which bypasses entity-access scoping entirely.
            create_default_legal_entities(tenant, validated_data["company_name"])
            roles = seed_default_roles(tenant)
            user.roles.add(roles["Owner"])
            TenantFeatures.objects.create(tenant=tenant, organization=True, cost_centers=True)

        return {"tenant": tenant, "user": user}


class TenantLoginSerializer(serializers.Serializer):
    subdomain = serializers.CharField()
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = authenticate(
            request=self.context.get("request"),
            subdomain=attrs["subdomain"].lower(),
            email=attrs["email"],
            password=attrs["password"],
        )
        if user is None:
            raise serializers.ValidationError(
                _("Invalid subdomain, email or password."), code="authorization"
            )
        if not user.is_active:
            raise serializers.ValidationError(_("This account is inactive."), code="authorization")
        attrs["user"] = user
        return attrs
