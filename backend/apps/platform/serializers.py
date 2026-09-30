from rest_framework import serializers

from apps.tenants.models import Tenant

from .models import AuditLog, Plan


class PlatformLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    totp_code = serializers.CharField(required=False, allow_blank=True)


class PlatformUserSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    email = serializers.EmailField(read_only=True)
    full_name = serializers.CharField(read_only=True)
    role = serializers.CharField(read_only=True)


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = (
            "id", "code", "name", "is_active", "max_users", "max_branches",
            "max_invoices_per_month", "storage_mb", "feature_organization",
            "feature_cost_centers", "feature_inventory", "feature_purchasing",
            "feature_hr", "feature_treasury", "feature_assets",
        )
        read_only_fields = ("id",)


class TenantAdminSerializer(serializers.ModelSerializer):
    plan_code = serializers.CharField(source="plan.code", read_only=True)
    # Backed by TenantAdminViewSet.get_queryset()'s annotate() (Count/Max)
    # instead of SerializerMethodField — see the comment there.
    user_count = serializers.IntegerField(read_only=True)
    invoice_count = serializers.IntegerField(read_only=True)
    last_activity = serializers.DateTimeField(read_only=True)

    class Meta:
        model = Tenant
        fields = (
            "id", "name", "subdomain", "plan", "plan_code", "status",
            "trial_ends_at", "user_count", "invoice_count", "last_activity",
            "created_at",
        )
        read_only_fields = (
            # Sprint 6.9.1 (item I, decision 7): "غير قابل للتغيير بعد
            # الإنشاء عبر أي API" — TenantAdminViewSet currently has no
            # PATCH/PUT route at all (http_method_names below), so this
            # was already unreachable in practice; read-only here too,
            # defensively, so a future update route can't regress it
            # without deliberately overriding this serializer's field.
            "id", "subdomain", "plan_code", "user_count", "invoice_count", "last_activity", "created_at",
        )


class ChangePlanSerializer(serializers.Serializer):
    # Sprint 6.6.3 (item 1): must resolve via the same "platform" alias
    # TenantAdminViewSet.change_plan's own `tenant` was loaded from —
    # assigning a "default"-loaded Plan to a "platform"-loaded Tenant's
    # FK trips Django's cross-database relation guard.
    plan = serializers.PrimaryKeyRelatedField(queryset=Plan.objects.using("platform").filter(is_active=True))


class ExtendTrialSerializer(serializers.Serializer):
    trial_ends_at = serializers.DateTimeField()


class SuspendTenantSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=3)


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = (
            "id", "actor_type", "actor_id", "action", "target_type", "target_id",
            "tenant_id", "before", "after", "ip_address", "user_agent", "created_at",
        )
        read_only_fields = fields
