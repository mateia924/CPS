import decimal

from django.db.models import Sum
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.common.constants import (
    MONEY_DECIMAL_PLACES,
    MONEY_MAX_DIGITS,
    RATE_DECIMAL_PLACES,
    RATE_MAX_DIGITS,
)
from apps.organization.models import LegalEntity
from apps.organization.services import get_accessible_entity_ids

from .models import Account, JournalEntry, JournalLine, TaxCode, TaxPeriod
from .services import REPORTABLE_STATUSES


class AccountSerializer(serializers.ModelSerializer):
    """دليل الحسابات (3.4/3.18): أساسي = كود/اسم/نوع/أب؛ متقدم =
    normal_balance/allow_posting/is_intercompany (القاعدة 7)."""

    is_leaf = serializers.BooleanField(read_only=True)

    class Meta:
        model = Account
        fields = (
            "id", "parent", "level", "code", "name", "type", "normal_balance",
            "allow_posting", "is_intercompany", "system_key", "is_system", "party",
            "is_leaf", "is_active", "created_at",
        )
        read_only_fields = ("id", "level", "system_key", "is_system", "party", "is_leaf", "created_at")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            self.fields["parent"].queryset = Account.objects.filter(tenant=request.user.tenant)

    def validate(self, attrs):
        parent = attrs.get("parent", getattr(self.instance, "parent", None))
        account_type = attrs.get("type", getattr(self.instance, "type", None))
        if parent is not None and parent.type != account_type:
            raise serializers.ValidationError(
                {"parent": [_("An account must have the same type as its parent.")]}
            )
        return attrs

    def update(self, instance, validated_data):
        # 3.15.9: "حساب عليه سطور لا يُحذف ولا يُغيَّر نوعه ولا أبوه".
        # Deletion is already protected at the DB level
        # (JournalLine.account is on_delete=PROTECT, turned into a 409
        # by SoftDeleteViewSetMixin) — this covers the other two.
        if instance.journal_lines.exists():
            if "type" in validated_data and validated_data["type"] != instance.type:
                raise serializers.ValidationError(
                    {"type": [_("Cannot change the type of an account with posted lines.")]}
                )
            if "parent" in validated_data and validated_data["parent"] != instance.parent:
                raise serializers.ValidationError(
                    {"parent": [_("Cannot change the parent of an account with posted lines.")]}
                )
        return super().update(instance, validated_data)


class AccountTreeSerializer(serializers.ModelSerializer):
    """دليل الحسابات: شجرة قابلة للطي مع الأرصدة الحالية — نفس نمط
    LegalEntityTreeSerializer/CostCenterTreeSerializer."""

    children = serializers.SerializerMethodField()
    balance = serializers.SerializerMethodField()

    class Meta:
        model = Account
        fields = (
            "id", "code", "name", "type", "normal_balance", "is_system", "system_key",
            "is_active", "balance", "children",
        )

    def get_children(self, obj):
        return AccountTreeSerializer(obj.children.order_by("code"), many=True, context=self.context).data

    def get_balance(self, obj):
        totals = obj.journal_lines.filter(entry__status__in=REPORTABLE_STATUSES).aggregate(
            debit=Sum("debit"), credit=Sum("credit")
        )
        debit = totals["debit"] or 0
        credit = totals["credit"] or 0
        signed = (debit - credit) if obj.normal_balance == Account.NormalBalance.DEBIT else (credit - debit)
        return str(signed)


class JournalLineSerializer(serializers.ModelSerializer):
    account_code = serializers.CharField(source="account.code", read_only=True)
    account_name = serializers.CharField(source="account.name", read_only=True)
    account_system_key = serializers.CharField(source="account.system_key", read_only=True)

    class Meta:
        model = JournalLine
        fields = (
            "id", "account", "account_code", "account_name", "account_system_key",
            "cost_center", "party", "description", "debit", "credit", "debit_fc", "credit_fc",
        )
        read_only_fields = fields


class JournalEntrySerializer(serializers.ModelSerializer):
    lines = JournalLineSerializer(many=True, read_only=True)
    legal_entity_name = serializers.CharField(source="legal_entity.name", read_only=True)

    class Meta:
        model = JournalEntry
        fields = (
            "id", "legal_entity", "legal_entity_name", "date", "memo", "reference", "number",
            "status", "created_by", "reverses", "source_type", "source_id",
            "currency", "exchange_rate", "created_at", "lines",
        )
        read_only_fields = fields


# ---------------------------------------------------------------------
# Sprint 4.4: "القيود اليدوية" screen — create() only builds a DRAFT
# entry; submit/approve/post/reverse are separate actions
# (accounting/views.py), each a plain state transition with no input.
# ---------------------------------------------------------------------


class ManualJournalLineInputSerializer(serializers.Serializer):
    # Bare UUID, not PrimaryKeyRelatedField — same reasoning as
    # InvoiceLineInputSerializer.product: this is nested inside
    # ManualJournalEntryCreateSerializer, declared before any request
    # context exists, so a tenant-scoped queryset can't be bound here.
    # Tenant scoping is enforced explicitly in create() instead.
    account = serializers.UUIDField()
    cost_center = serializers.UUIDField(required=False, allow_null=True)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    debit_fc = serializers.DecimalField(
        max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, min_value=0,
        default=decimal.Decimal("0"),
    )
    credit_fc = serializers.DecimalField(
        max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, min_value=0,
        default=decimal.Decimal("0"),
    )

    def validate(self, attrs):
        if attrs["debit_fc"] and attrs["credit_fc"]:
            raise serializers.ValidationError(_("A line cannot have both a debit and a credit amount."))
        if not attrs["debit_fc"] and not attrs["credit_fc"]:
            raise serializers.ValidationError(_("A line needs either a debit or a credit amount."))
        return attrs


class ManualJournalEntryCreateSerializer(serializers.Serializer):
    legal_entity = serializers.PrimaryKeyRelatedField(queryset=LegalEntity.objects.none())
    date = serializers.DateField()
    currency = serializers.CharField(max_length=3, required=False)
    exchange_rate = serializers.DecimalField(
        max_digits=RATE_MAX_DIGITS, decimal_places=RATE_DECIMAL_PLACES, required=False
    )
    memo = serializers.CharField(required=False, allow_blank=True, default="")
    reference = serializers.CharField(required=False, allow_blank=True, default="")
    lines = ManualJournalLineInputSerializer(many=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            accessible_ids = get_accessible_entity_ids(request.user)
            self.fields["legal_entity"].queryset = LegalEntity.objects.filter(
                tenant=request.user.tenant, id__in=accessible_ids
            )

    def validate_lines(self, value):
        if len(value) < 2:
            raise serializers.ValidationError(_("At least two lines are required."))
        return value


class JournalEntryReverseSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=3)


class TaxCodeSerializer(serializers.ModelSerializer):
    """أكواد الضريبة (3.16.2): "قراءة + تعديل الاسم/التفعيل؛ إضافة كود
    جديد للمدير المالي" — rate/kind/direction/deductible/account are
    read-only after creation (a code's meaning shouldn't drift under
    invoices that already reference it); only name/is_active are ever
    PATCHable, matching the spec's own restriction."""

    class Meta:
        model = TaxCode
        fields = (
            "id", "code", "name", "rate", "kind", "direction", "deductible", "account",
            "country_code", "effective_from", "is_active", "created_at",
        )
        read_only_fields = ("id", "created_at")

    def update(self, instance, validated_data):
        allowed = {"name", "is_active"}
        blocked = set(validated_data) - allowed
        if blocked:
            raise serializers.ValidationError(
                {field: [_("Only name and is_active can be edited after creation.")] for field in blocked}
            )
        return super().update(instance, validated_data)


class TaxPeriodSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxPeriod
        fields = (
            "id", "legal_entity", "period_type", "start", "end", "status", "filed_at",
            "reference", "created_at",
        )
        read_only_fields = fields
