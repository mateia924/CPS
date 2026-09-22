from rest_framework import serializers

from .models import DocumentNumberingSetting


class DocumentNumberingSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentNumberingSetting
        fields = ("id", "doc_type", "prefix", "reset_yearly")
        read_only_fields = ("id", "doc_type")
