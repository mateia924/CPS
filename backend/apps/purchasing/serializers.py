from decimal import Decimal

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from .models import PurchaseSettings, WithholdingTaxCode


class PurchaseSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseSettings
        fields = ("match_tolerance_pct", "match_tolerance_amount", "default_grni_policy")

    def validate_match_tolerance_pct(self, value):
        if not Decimal("0") <= value <= Decimal("100"):
            raise serializers.ValidationError(_("The tolerance percentage must be between 0 and 100."))
        return value

    def validate_match_tolerance_amount(self, value):
        if value < 0:
            raise serializers.ValidationError(_("The tolerance amount cannot be negative."))
        return value


class WithholdingTaxCodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = WithholdingTaxCode
        fields = ("id", "country", "code", "name_ar", "rate", "base", "applies_to", "is_example", "is_active")
        read_only_fields = fields
