from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from .models import CostCenter, LegalEntity


def _validate_no_cycle(instance, parent, label):
    # `instance` is None on create — a brand-new node can't already be
    # an ancestor of anything, so there's nothing to check yet.
    if parent is None or instance is None:
        return
    if parent.id == instance.id:
        raise serializers.ValidationError({"parent": [_("An entity cannot be its own parent.")]})
    node = parent
    seen = set()
    while node is not None:
        if node.id == instance.id or node.id in seen:
            raise serializers.ValidationError(
                {"parent": [_("This would create a cycle in the %(label)s tree.") % {"label": label}]}
            )
        seen.add(node.id)
        node = node.parent


class LegalEntitySerializer(serializers.ModelSerializer):
    class Meta:
        model = LegalEntity
        fields = (
            "id", "parent", "code", "name", "entity_type", "country_code",
            "tax_number", "base_currency", "is_active", "created_at",
        )
        read_only_fields = ("id", "created_at")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # `parent` defaults to LegalEntity.objects.all() (every tenant) —
        # must be scoped, same pattern as InvoiceCreateSerializer.customer.
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            self.fields["parent"].queryset = LegalEntity.objects.filter(
                tenant=request.user.tenant
            )

    def validate(self, attrs):
        parent = attrs.get("parent", getattr(self.instance, "parent", None))
        if parent is not None and parent.entity_type == LegalEntity.Type.BRANCH:
            raise serializers.ValidationError(
                {"parent": [_("A branch cannot have child entities.")]}
            )
        _validate_no_cycle(self.instance, parent, "legal entity")
        return attrs


class LegalEntityTreeSerializer(serializers.ModelSerializer):
    """Renders a subtree, restricted to context["visible_ids"] when
    given (entity-scoped users — see organization/views.py: a node whose
    real children aren't all visible must not leak them here)."""

    children = serializers.SerializerMethodField()

    class Meta:
        model = LegalEntity
        fields = ("id", "code", "name", "entity_type", "is_active", "children")

    def get_children(self, obj):
        qs = obj.children.all()
        visible_ids = self.context.get("visible_ids")
        if visible_ids is not None:
            qs = qs.filter(id__in=visible_ids)
        return LegalEntityTreeSerializer(qs.order_by("code"), many=True, context=self.context).data


class CostCenterSerializer(serializers.ModelSerializer):
    class Meta:
        model = CostCenter
        fields = ("id", "parent", "code", "name", "center_type", "is_active", "created_at")
        read_only_fields = ("id", "created_at")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            self.fields["parent"].queryset = CostCenter.objects.filter(
                tenant=request.user.tenant
            )

    def validate(self, attrs):
        parent = attrs.get("parent", getattr(self.instance, "parent", None))
        _validate_no_cycle(self.instance, parent, "cost center")
        return attrs


class CostCenterTreeSerializer(serializers.ModelSerializer):
    children = serializers.SerializerMethodField()

    class Meta:
        model = CostCenter
        fields = ("id", "code", "name", "center_type", "is_active", "children")

    def get_children(self, obj):
        return CostCenterTreeSerializer(obj.children.all().order_by("code"), many=True).data
