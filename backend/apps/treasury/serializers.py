from rest_framework import serializers

from apps.organization.models import LegalEntity
from apps.parties.models import Party, PartyRole

from .models import Bank, CashBox, Custody, ExchangeRate


def _employee_party_queryset(tenant):
    return Party.objects.filter(
        tenant=tenant, roles__role=PartyRole.Role.EMPLOYEE, roles__is_active=True
    )


class _TenantScopedRelationsMixin:
    """Scopes `legal_entity` (every model here) and any employee/party
    relation field named in `party_fields` to the caller's own tenant —
    same pattern as InvoiceCreateSerializer.customer."""

    party_fields: tuple[str, ...] = ()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            tenant = request.user.tenant
            if "legal_entity" in self.fields:
                self.fields["legal_entity"].queryset = LegalEntity.objects.filter(tenant=tenant)
            for field_name in self.party_fields:
                self.fields[field_name].queryset = _employee_party_queryset(tenant)


class BankSerializer(_TenantScopedRelationsMixin, serializers.ModelSerializer):
    class Meta:
        model = Bank
        fields = (
            "id", "legal_entity", "name", "bank_name", "account_number", "iban", "swift",
            "currency", "is_active", "created_at",
        )
        read_only_fields = ("id", "created_at")


class CashBoxSerializer(_TenantScopedRelationsMixin, serializers.ModelSerializer):
    party_fields = ("custodian",)

    class Meta:
        model = CashBox
        fields = (
            "id", "legal_entity", "name", "currency", "custodian", "max_balance", "is_active", "created_at",
        )
        read_only_fields = ("id", "created_at")


class CustodySerializer(_TenantScopedRelationsMixin, serializers.ModelSerializer):
    party_fields = ("employee",)

    class Meta:
        model = Custody
        fields = (
            "id", "legal_entity", "employee", "name", "currency", "is_active", "created_at",
        )
        read_only_fields = ("id", "created_at")


class ExchangeRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExchangeRate
        fields = (
            "id", "from_currency", "to_currency", "date", "rate", "source", "created_by", "created_at",
        )
        read_only_fields = ("id", "created_by", "created_at")

    def validate(self, attrs):
        if attrs.get("from_currency") == attrs.get("to_currency"):
            raise serializers.ValidationError(
                {"to_currency": ["From/to currency must be different — same-currency rate is always 1."]}
            )
        return attrs
