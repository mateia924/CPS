import decimal

from django.core.exceptions import ValidationError as DjangoValidationError
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

from .models import Account, FiscalPeriod, FiscalYear, JournalEntry, JournalLine, TaxCode, TaxPeriod
from .periods import create_fiscal_year_with_periods
from .services import REPORTABLE_STATUSES


class AccountSerializer(serializers.ModelSerializer):
    """دليل الحسابات (3.4/3.18): أساسي = كود/اسم/نوع/أب؛ متقدم =
    normal_balance/allow_posting/is_intercompany (القاعدة 7)."""

    is_leaf = serializers.BooleanField(read_only=True)

    class Meta:
        model = Account
        fields = (
            "id", "parent", "level", "code", "name", "type", "normal_balance",
            "allow_posting", "allow_manual_posting", "is_intercompany", "system_key", "is_system", "party",
            "is_leaf", "is_active", "created_at",
        )
        read_only_fields = (
            "id", "level", "system_key", "is_system", "party", "is_leaf", "created_at",
            "allow_manual_posting",
        )

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
            "allow_manual_posting", "is_active", "balance", "children",
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
    # CFO_REVIEW_1 C2 — required only when a line targets a control
    # account (`Account.allow_manual_posting=False`); validated against
    # that condition in the view, not here (needs resolved Account
    # objects first).
    override_reason = serializers.CharField(required=False, allow_blank=True, default="")
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
    # CFO_REVIEW_1 C8: defaults to today in the service layer when
    # omitted; validated there too (must not precede the original
    # entry's own date) since that check needs the entry itself.
    date = serializers.DateField(required=False)


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


class FiscalPeriodSerializer(serializers.ModelSerializer):
    class Meta:
        model = FiscalPeriod
        fields = (
            "id", "fiscal_year", "seq", "start_date", "end_date", "status",
            "closed_by", "closed_at", "close_note", "close_snapshot",
            "reopened_by", "reopened_at", "reopened_reason",
            "locked_by", "locked_at", "lock_attestation",
        )
        read_only_fields = fields


class FiscalYearSerializer(serializers.ModelSerializer):
    periods = FiscalPeriodSerializer(many=True, read_only=True)

    class Meta:
        model = FiscalYear
        fields = ("id", "name", "start_date", "end_date", "status", "is_auto_created", "periods", "created_at")
        read_only_fields = ("id", "status", "is_auto_created", "periods", "created_at")


class FiscalYearWriteSerializer(serializers.Serializer):
    """Sprint 6.1 (decision 1): create ("CRUD مقيَّد") always builds the
    year AND its periods together in one atomic call — a bare
    `FiscalYear` row with no periods is never a valid state this API
    can produce. PATCH reuses the same shape: boundaries only move
    together with a full period regeneration (see the view)."""

    name = serializers.CharField(max_length=50)
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    period_length = serializers.ChoiceField(choices=["monthly", "quarterly", "custom"], default="monthly")
    custom_period_end_dates = serializers.ListField(child=serializers.DateField(), required=False)

    def create(self, validated_data):
        tenant = self.context["request"].user.tenant
        try:
            return create_fiscal_year_with_periods(
                tenant=tenant,
                name=validated_data["name"],
                start_date=validated_data["start_date"],
                end_date=validated_data["end_date"],
                period_length=validated_data["period_length"],
                custom_period_end_dates=validated_data.get("custom_period_end_dates"),
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict if hasattr(exc, "message_dict") else {"detail": [str(exc)]})
