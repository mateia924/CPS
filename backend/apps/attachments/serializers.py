from rest_framework import serializers

from .models import Attachment
from .services import ALLOWED_TARGETS


class AttachmentUploadSerializer(serializers.Serializer):
    target_type = serializers.ChoiceField(choices=list(ALLOWED_TARGETS))
    target_id = serializers.UUIDField()
    category = serializers.ChoiceField(choices=Attachment.Category.choices)
    file = serializers.FileField()
    description = serializers.CharField(required=False, allow_blank=True, default="")


class AttachmentSerializer(serializers.ModelSerializer):
    target_type = serializers.SerializerMethodField()
    uploaded_by_email = serializers.CharField(source="uploaded_by.email", read_only=True, default="")
    voided_by_email = serializers.CharField(source="voided_by.email", read_only=True, default="")

    class Meta:
        model = Attachment
        fields = (
            "id", "target_type", "object_id", "category", "description",
            "original_name", "mime_type", "size", "sha256",
            "uploaded_by_email", "uploaded_at",
            "status", "void_reason", "voided_by_email", "voided_at",
            "version", "supersedes",
            "scan_status", "scanned_at", "integrity_status",
        )
        read_only_fields = fields

    def get_target_type(self, obj):
        for key, (app_label, model_name) in ALLOWED_TARGETS.items():
            if obj.content_type.app_label == app_label and obj.content_type.model == model_name:
                return key
        return None


class VoidAttachmentSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=3)
