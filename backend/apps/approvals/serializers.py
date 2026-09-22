from rest_framework import serializers

from apps.access.models import Role

from .models import ApprovalRule


class ApprovalRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApprovalRule
        fields = ("id", "doc_type", "min_amount", "required_role", "is_active", "created_at")
        read_only_fields = ("id", "created_at")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            self.fields["required_role"].queryset = Role.objects.filter(tenant=request.user.tenant)


class RejectDocumentSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=3)
