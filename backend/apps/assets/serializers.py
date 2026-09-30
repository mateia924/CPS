from decimal import Decimal

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.accounting.models import Account
from apps.common.constants import MONEY_DECIMAL_PLACES, MONEY_MAX_DIGITS
from apps.organization.models import CostCenter, LegalEntity
from apps.organization.services import get_or_create_linked_cost_center
from apps.parties.models import Party, PartyRole

from .models import Asset, AssetAddition, AssetDisposal, AssetTransfer


class AssetAdditionSerializer(serializers.ModelSerializer):
    """Sprint 6.5 (decision 6): read shape for both the create response
    and the addition-history list nested on AssetSerializer below."""

    class Meta:
        model = AssetAddition
        fields = (
            "id", "date", "amount_base", "description", "extend_life_months",
            "old_entry", "new_entry", "created_by", "created_at",
        )
        read_only_fields = fields


class AssetAdditionCreateSerializer(serializers.Serializer):
    date = serializers.DateField()
    amount_base = serializers.DecimalField(max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    extend_life_months = serializers.IntegerField(required=False, default=0, min_value=0)


class AssetDisposalSerializer(serializers.ModelSerializer):
    """Sprint 6.5 (decision 7): read shape for both the create response
    and the disposal-history list nested on AssetSerializer below."""

    class Meta:
        model = AssetDisposal
        fields = (
            "id", "date", "fraction", "proceeds_base", "proceeds_account", "proceeds_party",
            "proceeds_party_role", "reason", "cost_share", "accum_share", "gain_loss", "journal_entry",
            "status", "created_by", "created_at",
        )
        read_only_fields = fields


class AssetDisposeCreateSerializer(serializers.Serializer):
    date = serializers.DateField()
    fraction = serializers.DecimalField(max_digits=5, decimal_places=4, min_value=Decimal("0.0001"))
    proceeds_base = serializers.DecimalField(
        max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, required=False, default=Decimal("0")
    )
    proceeds_account = serializers.PrimaryKeyRelatedField(
        queryset=Account.objects.all(), required=False, allow_null=True, default=None
    )
    proceeds_party = serializers.PrimaryKeyRelatedField(
        queryset=Party.objects.all(), required=False, allow_null=True, default=None
    )
    proceeds_party_role = serializers.CharField(required=False, allow_blank=True, default="")
    reason = serializers.CharField(required=False, allow_blank=True, default="")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            tenant = request.user.tenant
            self.fields["proceeds_account"].queryset = Account.objects.filter(tenant=tenant)
            self.fields["proceeds_party"].queryset = Party.objects.filter(tenant=tenant)


class AssetTransferSerializer(serializers.ModelSerializer):
    """Sprint 6.5 (decision 8): read shape for both the create response
    and the transfer-history list nested on AssetSerializer below."""

    class Meta:
        model = AssetTransfer
        fields = (
            "id", "from_legal_entity", "to_legal_entity", "from_cost_center", "to_cost_center",
            "reason", "created_by", "created_at",
        )
        read_only_fields = fields


class AssetTransferCreateSerializer(serializers.Serializer):
    legal_entity = serializers.PrimaryKeyRelatedField(
        queryset=LegalEntity.objects.all(), required=False, allow_null=True, default=None
    )
    cost_center = serializers.PrimaryKeyRelatedField(
        queryset=CostCenter.objects.all(), required=False, allow_null=True, default=None
    )
    # Sprint 6.5.18 (UAT item 9): "فورم النقل ... يطلب سببًا".
    reason = serializers.CharField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            tenant = request.user.tenant
            self.fields["legal_entity"].queryset = LegalEntity.objects.filter(tenant=tenant)
            self.fields["cost_center"].queryset = CostCenter.objects.filter(tenant=tenant)


class HistoricalInstallmentSerializer(serializers.Serializer):
    """Sprint 6.5.18 (items 3, 9): read shape for
    apps.assets.depreciation.historical_installments — a generated
    installment from a schedule version the asset no longer uses."""

    id = serializers.UUIDField()
    seq = serializers.IntegerField()
    due_date = serializers.DateField()
    amount_base = serializers.DecimalField(max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES)
    journal_entry = serializers.UUIDField(allow_null=True)
    entry_description = serializers.CharField(source="entry.description")


class AssetSerializer(serializers.ModelSerializer):
    # Write-only (3.3 section 4): "افتراضيًا مفعّل للسيارات" — only
    # meaningful when category == VEHICLE; ignored otherwise.
    create_linked_cost_center = serializers.BooleanField(required=False, default=True, write_only=True)
    additions = AssetAdditionSerializer(many=True, read_only=True)
    disposals = AssetDisposalSerializer(many=True, read_only=True)
    transfers = AssetTransferSerializer(many=True, read_only=True)
    # Sprint 6.5.3: computed the same way apps.assets.depreciation.
    # add_to_asset itself derives book value — entry.total_amount_base
    # is always "book value at that entry's own start − salvage_base"
    # by construction, so this stays correct across any number of
    # additions without needing to walk old_entry/new_entry history.
    accumulated_depreciation = serializers.SerializerMethodField()
    book_value = serializers.SerializerMethodField()
    # Sprint 6.5.18 (items 3, 9): generated installments from a
    # schedule version the asset no longer uses — every version for a
    # fully disposed asset (depreciation_entry back to null), or just
    # the superseded ones for an asset an addition/partial disposal
    # has since rescheduled.
    historical_installments = serializers.SerializerMethodField()

    class Meta:
        model = Asset
        fields = (
            "id", "legal_entity", "code", "name", "category", "purchase_date", "purchase_cost",
            "currency", "useful_life_months", "salvage_value", "depreciation_method",
            "custodian", "cost_center", "status", "is_active", "created_at",
            "create_linked_cost_center",
            # Sprint 6.5 (decisions 3, 4, 5, 9): writable.
            "is_depreciable", "purchase_reference", "in_service_date",
            "declining_balance_rate", "opening_accumulated_depreciation",
            # Sprint 6.5: read-only — frozen/computed by
            # apps.assets.depreciation, never set directly here.
            "cost_base", "salvage_base", "disposed_fraction", "depreciation_entry",
            # Sprint 6.5.3 (decision 6): addition history — "سجل
            # الإضافات" on the asset detail screen.
            "additions", "accumulated_depreciation", "book_value", "historical_installments",
            # Sprint 6.5.4 (decision 7): disposal history.
            "disposals",
            # Sprint 6.5.5 (decision 8): transfer history.
            "transfers",
        )
        read_only_fields = (
            "id", "created_at", "cost_base", "salvage_base", "disposed_fraction", "depreciation_entry", "additions",
            "accumulated_depreciation", "book_value", "historical_installments", "disposals", "transfers",
        )

    def get_book_value(self, asset):
        from .depreciation import current_book_value

        return str(current_book_value(asset))

    def get_accumulated_depreciation(self, asset):
        from .depreciation import current_book_value

        cost = asset.cost_base if asset.cost_base is not None else asset.purchase_cost
        return str(cost - current_book_value(asset))

    def get_historical_installments(self, asset):
        from .depreciation import historical_installments

        rows = [
            {
                "id": installment.id, "seq": installment.seq, "due_date": installment.due_date,
                "amount_base": installment.amount_base, "journal_entry": installment.journal_entry_id,
                "entry": installment.entry,
            }
            for installment in historical_installments(asset)
        ]
        return HistoricalInstallmentSerializer(rows, many=True).data

    def validate(self, attrs):
        # Sprint 6.5 (decision text under 6.5.0): "salvage_value <
        # purchase_cost، useful_life_months ≥ 1، declining_balance_rate
        # إلزامي فقط مع المتناقص وضمن (0، 100)" — a PATCH may omit any
        # of these, so fall back to the existing instance's value.
        def _value(name):
            return attrs.get(name, getattr(self.instance, name, None) if self.instance else None)

        purchase_cost = _value("purchase_cost")
        salvage_value = _value("salvage_value")
        if purchase_cost is not None and salvage_value is not None and salvage_value >= purchase_cost:
            raise serializers.ValidationError(
                {"salvage_value": [_("القيمة التخريدية يجب أن تكون أقل من تكلفة الشراء.")]}
            )

        useful_life_months = _value("useful_life_months")
        if useful_life_months is not None and useful_life_months < 1:
            raise serializers.ValidationError(
                {"useful_life_months": [_("العمر الإنتاجي يجب أن يكون شهرًا واحدًا على الأقل.")]}
            )

        method = _value("depreciation_method")
        rate = _value("declining_balance_rate")
        if method == Asset.DepreciationMethod.DECLINING_BALANCE:
            if rate is None:
                raise serializers.ValidationError(
                    {"declining_balance_rate": [_("معدّل الإهلاك المتناقص إلزامي مع هذه الطريقة.")]}
                )
            if not (Decimal("0") < rate < Decimal("100")):
                raise serializers.ValidationError(
                    {"declining_balance_rate": [_("معدّل الإهلاك المتناقص يجب أن يكون بين 0 و100.")]}
                )
        return attrs

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            tenant = request.user.tenant
            self.fields["legal_entity"].queryset = LegalEntity.objects.filter(tenant=tenant)
            self.fields["custodian"].queryset = Party.objects.filter(
                tenant=tenant, roles__role=PartyRole.Role.EMPLOYEE, roles__is_active=True
            )
            self.fields["cost_center"].queryset = CostCenter.objects.filter(tenant=tenant)

    def create(self, validated_data):
        create_linked = validated_data.pop("create_linked_cost_center", True)
        asset = super().create(validated_data)
        if create_linked and asset.category == Asset.Category.VEHICLE and asset.cost_center is None:
            linked = get_or_create_linked_cost_center(
                tenant=asset.tenant,
                linked_object=asset,
                code=f"CC-{asset.code}",
                name=asset.name,
                center_type=CostCenter.Type.VEHICLE,
            )
            asset.cost_center = linked
            asset.save(update_fields=["cost_center"])
        return asset

    def update(self, instance, validated_data):
        validated_data.pop("create_linked_cost_center", None)
        return super().update(instance, validated_data)
