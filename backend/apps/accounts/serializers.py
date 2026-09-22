from datetime import timedelta

from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.access.services import seed_default_roles
from apps.accounting.services import seed_chart_of_accounts
from apps.approvals.models import ApprovalRule
from apps.organization.services import create_default_legal_entities
from apps.platform.models import AuditLog, Plan
from apps.platform.services import log_action
from apps.tenants.models import Tenant
from apps.tenants.services import apply_plan_to_tenant

from .models import User

TRIAL_LENGTH_DAYS = 14


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
    # Sprint 4.3 (3.4): "نوع النشاط" — basic field at registration,
    # selects which chart-of-accounts template seed_chart_of_accounts
    # applies. Defaults to the small-client-first persona (3.13).
    business_type = serializers.ChoiceField(
        choices=Tenant.BusinessType.choices, required=False, default=Tenant.BusinessType.SERVICE
    )

    def validate_subdomain(self, value):
        value = value.lower()
        if Tenant.objects.filter(subdomain=value).exists():
            raise serializers.ValidationError(_("This subdomain is already taken."))
        return value

    def create(self, validated_data):
        with transaction.atomic():
            # Sprint 2 (3.14): every new self-registered tenant starts on
            # Free + Trial — not explicitly stated in the sprint spec
            # (which only says pre-sprint-2 tenants get grandfathered
            # onto Enterprise), but the obvious, industry-standard
            # default for a brand-new signup; logged in the Decision Log.
            free_plan = Plan.objects.get(code="free")
            tenant = Tenant.objects.create(
                name=validated_data["company_name"],
                subdomain=validated_data["subdomain"],
                plan=free_plan,
                status=Tenant.Status.TRIAL,
                trial_ends_at=timezone.now() + timedelta(days=TRIAL_LENGTH_DAYS),
                business_type=validated_data["business_type"],
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
            apply_plan_to_tenant(tenant, free_plan)

            # Sprint 4.5 (3.15.9): "لا قيد يدوي يُرحَّل بلا اعتماد" — every
            # tenant starts with this baseline rule so manual JVs always
            # need Owner approval by default; editable/removable
            # afterward via Settings ← "قواعد الاعتماد".
            ApprovalRule.objects.create(
                tenant=tenant, doc_type=ApprovalRule.DocType.JOURNAL_ENTRY,
                min_amount=0, required_role=roles["Owner"],
            )

        return {"tenant": tenant, "user": user}


class TenantLoginSerializer(serializers.Serializer):
    subdomain = serializers.CharField()
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        request = self.context.get("request")
        user = authenticate(
            request=request,
            subdomain=attrs["subdomain"].lower(),
            email=attrs["email"],
            password=attrs["password"],
        )
        if user is None or not user.is_active:
            # Sprint 2 (3.14): "يُسجَّل تلقائيًا ... تسجيل الدخول/الفشل" —
            # tenant_id is only known here if the subdomain itself
            # resolved to a real tenant; a typo'd subdomain leaves it
            # None rather than guessing.
            tenant = Tenant.objects.filter(subdomain=attrs["subdomain"].lower()).first()
            log_action(
                actor_type=AuditLog.ActorType.TENANT_USER,
                actor_id=None,
                action="tenant_user.login_failed",
                tenant_id=tenant.id if tenant else None,
                after={"email": attrs["email"]},
                request=request,
            )
            if user is None:
                raise serializers.ValidationError(
                    _("Invalid subdomain, email or password."), code="authorization"
                )
            raise serializers.ValidationError(_("This account is inactive."), code="authorization")

        attrs["user"] = user
        log_action(
            actor_type=AuditLog.ActorType.TENANT_USER,
            actor_id=user.id,
            action="tenant_user.login",
            tenant_id=user.tenant_id,
            request=request,
        )
        return attrs
