from datetime import timedelta

from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.access.services import seed_default_roles
from apps.accounting.periods import seed_fiscal_year_for_tenant
from apps.accounting.services import (
    generate_tax_periods_for_year,
    seed_chart_of_accounts,
    seed_tax_codes_for_country,
)
from apps.approvals.models import ApprovalRule
from apps.common.validators import validate_tenant_subdomain
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
        # Sprint 6 (block 6.0, item 6): `status`/`past_due_since` added
        # so the frontend can show the PAST_DUE warning banner from
        # /api/auth/me/ without a second request.
        fields = ("id", "name", "subdomain", "status", "past_due_since", "created_at")
        read_only_fields = fields


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = (
            "id", "email", "first_name", "last_name", "role", "date_joined",
            "notify_approvals_email", "must_change_password", "totp_confirmed",
        )
        read_only_fields = fields


class RegisterSerializer(serializers.Serializer):
    company_name = serializers.CharField(max_length=255)
    subdomain = serializers.CharField(max_length=30)
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
        try:
            value = validate_tenant_subdomain(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message)
        if Tenant.objects.filter(subdomain=value).exists():
            raise serializers.ValidationError(_("هذا الاسم مُستخدَم بالفعل، اختر اسمًا آخر."))
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
            _company, branch = create_default_legal_entities(tenant, validated_data["company_name"])
            roles = seed_default_roles(tenant)
            user.roles.add(roles["Owner"])
            apply_plan_to_tenant(tenant, free_plan)

            # Sprint 4.6 (3.11/3.16.2): "حزمة الامتثال السعودية ... تُبذر
            # لكل مستأجر سعودي عند التسجيل" — keyed off the default
            # branch's country (every LegalEntity defaults to SA today).
            seed_tax_codes_for_country(tenant, branch.country_code)
            generate_tax_periods_for_year(branch, timezone.now().year)

            # Sprint 6.1 (decision 2): "لا مستأجر بلا سنة مالية في أي
            # لحظة" — a fresh calendar-year FiscalYear, 12 open monthly
            # periods, from the moment the tenant exists.
            seed_fiscal_year_for_tenant(tenant, start_date=timezone.now().date())

            # Sprint 4.5 (3.15.9): "لا قيد يدوي يُرحَّل بلا اعتماد" — every
            # tenant starts with this baseline rule so manual JVs always
            # need Owner approval by default; editable/removable
            # afterward via Settings ← "قواعد الاعتماد".
            ApprovalRule.objects.create(
                tenant=tenant, doc_type=ApprovalRule.DocType.JOURNAL_ENTRY,
                min_amount=0, required_role=roles["Owner"],
            )
            # Sprint 5.5 (block 5.5.0, CFO_REVIEW_1 C10 / 3.15.9): the
            # fixed IBAN-change rule — same reasoning as the JV rule
            # above, and same split as approvals/migrations/0005 (which
            # only backfills tenants that existed *before* this sprint).
            ApprovalRule.objects.create(
                tenant=tenant, doc_type=ApprovalRule.DocType.IBAN_CHANGE,
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


class ChangePasswordSerializer(serializers.Serializer):
    """Sprint 6.6.2 (item 2): both the forced must_change_password flow
    and the ordinary self-service "ملفي الشخصي" path use this — the
    caller already has a valid access token either way, so re-checking
    `current_password` is the only thing distinguishing "I meant to
    change this" from a stolen still-logged-in session."""

    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate_current_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError(_("Current password is incorrect."))
        return value

    def validate_new_password(self, value):
        user = self.context["request"].user
        if value.lower() == user.email.lower():
            raise serializers.ValidationError(_("The new password cannot be your email address."))
        validate_password(value, user=user)
        return value
