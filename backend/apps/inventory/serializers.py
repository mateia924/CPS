from rest_framework import serializers

from .models import InventorySettings


class InventorySettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = InventorySettings
        fields = (
            "allow_negative_stock",
            "expiry_alert_days",
            "freeze_warehouse_during_count",
            "default_tracking",
            "show_weight_karat_fields",
            "units_enabled",
            "barcode_enabled",
        )
