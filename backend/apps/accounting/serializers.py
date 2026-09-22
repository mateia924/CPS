from django.db.models import Sum
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from .models import Account, JournalEntry, JournalLine


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
        # No JournalEntry.status yet (sprint 4.4) — every entry that
        # exists today is effectively already posted (see
        # ARCH_REVIEW_1.md §3.2), so this sums every line without a
        # status filter for now; sprint 4.4 will add one.
        totals = obj.journal_lines.aggregate(debit=Sum("debit"), credit=Sum("credit"))
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
            "cost_center", "party", "debit", "credit", "debit_fc", "credit_fc",
        )
        read_only_fields = fields


class JournalEntrySerializer(serializers.ModelSerializer):
    lines = JournalLineSerializer(many=True, read_only=True)

    class Meta:
        model = JournalEntry
        fields = (
            "id", "legal_entity", "date", "memo", "source_type", "source_id",
            "currency", "exchange_rate", "created_at", "lines",
        )
        read_only_fields = fields
