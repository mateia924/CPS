from django.utils.translation import gettext_lazy as _
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

    def validate(self, attrs):
        # Sprint 6.6.5 (item 3): the DB-level guarantee (unique_
        # approval_rule_active_per_tenant_doctype_amount, ignoring
        # soft-deleted/deactivated rows the same way) is the real
        # backstop — this is just the friendly, same-request version
        # of that same check, so the form never has to round-trip a
        # raw IntegrityError.
        request = self.context.get("request")
        if request is None:
            return attrs
        doc_type = attrs.get("doc_type", getattr(self.instance, "doc_type", None))
        min_amount = attrs.get("min_amount", getattr(self.instance, "min_amount", None))
        duplicate = ApprovalRule.objects.filter(
            tenant=request.user.tenant, doc_type=doc_type, min_amount=min_amount,
            is_active=True, deleted_at__isnull=True,
        )
        if self.instance is not None:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise serializers.ValidationError(
                {
                    "min_amount": [
                        _(
                            "An active rule for this document type and minimum amount already exists."
                        )
                    ]
                }
            )
        return attrs


class RejectDocumentSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=3)
