from decimal import Decimal

from django.db import transaction
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.common.constants import MONEY_DECIMAL_PLACES, MONEY_MAX_DIGITS
from apps.organization.models import LegalEntity

from .models import Party, PartyRole
from .services import generate_party_code, link_employee_cost_center

# Sprint 3.5 field-name sentinel: distinguishes "the client didn't send
# this key at all" (leave the existing PartyRole.legal_entity alone,
# important for PATCH) from "the client explicitly sent null" (clear it).
_NOT_PROVIDED = object()

_ROLES_FIELD_REJECTED_MESSAGE = _(
    "This screen creates one specific role automatically — it does not "
    "accept a role field."
)


def _reject_roles_field(initial_data):
    """3.3 v1.4 / sprint 3.5: the UAT-rejected unified screen let the
    caller pick any role; each dedicated screen (Customers/Suppliers/
    Employees/Affiliates) now fixes its role server-side and must 400 if
    a client still sends one — same intent as PartySerializer above, but
    enforced here for the new per-role screens specifically."""
    if "roles" in initial_data or "role" in initial_data:
        raise serializers.ValidationError({"roles": [_ROLES_FIELD_REJECTED_MESSAGE]})


_PARTY_BASE_FIELDS = (
    "id", "code", "name", "name_en", "party_type", "tax_number",
    "national_id_or_cr", "phone", "email", "address", "country_code",
    "default_currency", "notes", "is_active", "roles", "created_at",
)
_PARTY_BASE_READ_ONLY = ("id", "code", "roles", "created_at")


class PartyRoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = PartyRole
        fields = ("id", "role", "is_active", "details", "legal_entity", "created_at")
        read_only_fields = ("id", "created_at")


class PartyRoleInputSerializer(serializers.Serializer):
    """Shared shape for the role added at Party creation and for the
    standalone add_role action."""

    role = serializers.ChoiceField(choices=PartyRole.Role.choices)
    details = serializers.JSONField(required=False, default=dict)
    legal_entity = serializers.PrimaryKeyRelatedField(
        queryset=LegalEntity.objects.none(), required=False, allow_null=True
    )
    # 3.3 section 4: "معطّل للموظفين" — opt-in, off by default, unlike
    # the vehicle asset case which defaults on.
    create_linked_cost_center = serializers.BooleanField(required=False, default=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            self.fields["legal_entity"].queryset = LegalEntity.objects.filter(
                tenant=request.user.tenant
            )

    def validate(self, attrs):
        if attrs["role"] == PartyRole.Role.AFFILIATE and not attrs.get("legal_entity"):
            raise serializers.ValidationError(
                {"legal_entity": [_("An affiliate role requires a matching legal entity.")]}
            )
        return attrs


class PartySerializer(serializers.ModelSerializer):
    roles = PartyRoleSerializer(many=True, read_only=True)
    # Write-only: the first role a new party is created with — 3.3's
    # frontend spec requires "دور واحد على الأقل" at creation time.
    role = serializers.ChoiceField(choices=PartyRole.Role.choices, write_only=True)
    role_details = serializers.JSONField(required=False, default=dict, write_only=True)
    role_legal_entity = serializers.PrimaryKeyRelatedField(
        queryset=LegalEntity.objects.none(), required=False, allow_null=True, write_only=True
    )
    role_create_linked_cost_center = serializers.BooleanField(
        required=False, default=False, write_only=True
    )

    class Meta:
        model = Party
        fields = (
            "id", "code", "name", "name_en", "party_type", "tax_number",
            "national_id_or_cr", "phone", "email", "address", "country_code",
            "default_currency", "notes", "is_active", "roles", "role",
            "role_details", "role_legal_entity", "role_create_linked_cost_center", "created_at",
        )
        read_only_fields = ("id", "code", "roles", "created_at")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            self.fields["role_legal_entity"].queryset = LegalEntity.objects.filter(
                tenant=request.user.tenant
            )
        # `role`/`role_details`/`role_legal_entity`/... only apply at
        # creation — editing an existing party's basic fields never
        # touches its roles (use the add_role action for that).
        if self.instance is not None:
            for field_name in (
                "role", "role_details", "role_legal_entity", "role_create_linked_cost_center"
            ):
                self.fields.pop(field_name, None)

    def validate(self, attrs):
        if self.instance is None and attrs.get("role") == PartyRole.Role.AFFILIATE and not attrs.get(
            "role_legal_entity"
        ):
            raise serializers.ValidationError(
                {"role_legal_entity": [_("An affiliate role requires a matching legal entity.")]}
            )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        role = validated_data.pop("role")
        role_details = validated_data.pop("role_details", {})
        role_legal_entity = validated_data.pop("role_legal_entity", None)
        create_linked_cost_center = validated_data.pop("role_create_linked_cost_center", False)
        # `tenant` arrives here via TenantScopedViewSet.perform_create's
        # `serializer.save(tenant=...)` kwarg, merged into validated_data
        # by DRF before create() is called — never trust request context
        # for it directly, same as every other tenant-scoped serializer.
        tenant = validated_data["tenant"]
        party = Party.objects.create(code=generate_party_code(tenant, role), **validated_data)
        PartyRole.objects.create(
            party=party, role=role, details=role_details, legal_entity=role_legal_entity
        )
        if role == PartyRole.Role.EMPLOYEE and create_linked_cost_center:
            link_employee_cost_center(party)
        return party


# ---------------------------------------------------------------------
# Sprint 3.5 (docs/SYSTEM_ANALYSIS.md 3.3 v1.4): one dedicated,
# role-fixed serializer per accountant-facing screen — Customers,
# Suppliers, Employees, Affiliates. Each shares the base Party fields
# above but never exposes `role`/`roles` as writable (see
# _reject_roles_field), and packs its own role-specific inputs into
# PartyRole.details (a flat JSON bag — same design as PartySerializer's
# role_details) except for the one genuine FK relation each needs.
# ---------------------------------------------------------------------


class _RoleDetailsMixin:
    """Shared read/write plumbing for the simple details-JSON-only
    screens (Customer, Supplier). Employee/Affiliate need a real FK
    (legal_entity) too, so they're written out by hand below instead of
    forcing them through this mixin."""

    role_const = None
    detail_field_names = ()

    def validate(self, attrs):
        _reject_roles_field(self.initial_data)
        return attrs

    def _pop_details(self, validated_data):
        # JSONField here uses the plain json.JSONEncoder (no
        # DjangoJSONEncoder), so Decimal isn't natively serializable —
        # stringify only that, not every value (an earlier version of
        # this stringified everything, turning payment_terms_days=30
        # into "30" on read too; caught in manual smoke-testing).
        details = {}
        for name in self.detail_field_names:
            if name in validated_data:
                value = validated_data.pop(name)
                details[name] = str(value) if isinstance(value, Decimal) else value
        return details

    @transaction.atomic
    def create(self, validated_data):
        details = self._pop_details(validated_data)
        tenant = validated_data["tenant"]
        party = Party.objects.create(code=generate_party_code(tenant, self.role_const), **validated_data)
        PartyRole.objects.create(party=party, role=self.role_const, details=details)
        return party

    @transaction.atomic
    def update(self, instance, validated_data):
        details = self._pop_details(validated_data)
        instance = super().update(instance, validated_data)
        if details:
            role = instance.roles.get(role=self.role_const)
            role.details = {**role.details, **details}
            role.save(update_fields=["details"])
        return instance

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        role = instance.roles.filter(role=self.role_const).first()
        details = role.details if role else {}
        for name in self.detail_field_names:
            rep[name] = details.get(name)
        return rep


class CustomerPartySerializer(_RoleDetailsMixin, serializers.ModelSerializer):
    """Backs `/api/parties/customers/` — the screen an accountant sees
    as simply "العملاء", no role concept visible at all."""

    role_const = PartyRole.Role.CUSTOMER
    detail_field_names = ("credit_limit", "payment_terms_days", "sales_rep")

    roles = PartyRoleSerializer(many=True, read_only=True)
    credit_limit = serializers.DecimalField(
        max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES,
        required=False, allow_null=True, write_only=True,
    )
    payment_terms_days = serializers.IntegerField(required=False, allow_null=True, write_only=True)
    sales_rep = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = Party
        fields = _PARTY_BASE_FIELDS + ("credit_limit", "payment_terms_days", "sales_rep")
        read_only_fields = _PARTY_BASE_READ_ONLY


class SupplierPartySerializer(_RoleDetailsMixin, serializers.ModelSerializer):
    """Backs `/api/parties/suppliers/`."""

    role_const = PartyRole.Role.SUPPLIER
    detail_field_names = ("payment_terms_days", "iban")

    roles = PartyRoleSerializer(many=True, read_only=True)
    payment_terms_days = serializers.IntegerField(required=False, allow_null=True, write_only=True)
    # 3.15.9: changing a supplier's IBAN is meant to require approval —
    # the approval engine doesn't exist yet (sprint 4), so this field is
    # a plain editable value for now. Documented as deferred, not
    # silently dropped.
    iban = serializers.CharField(required=False, allow_blank=True, write_only=True, max_length=34)

    class Meta:
        model = Party
        fields = _PARTY_BASE_FIELDS + ("payment_terms_days", "iban")
        read_only_fields = _PARTY_BASE_READ_ONLY


class EmployeePartySerializer(serializers.ModelSerializer):
    """Backs `/api/parties/employees/`. Unlike Customer/Supplier, this
    one also sets PartyRole.legal_entity (reused here as "which branch",
    see the model docstring) and optionally auto-links a cost center."""

    roles = PartyRoleSerializer(many=True, read_only=True)
    hire_date = serializers.DateField(required=False, allow_null=True, write_only=True)
    job_title = serializers.CharField(required=False, allow_blank=True, write_only=True)
    direct_manager = serializers.CharField(required=False, allow_blank=True, write_only=True)
    salary_currency = serializers.CharField(
        required=False, allow_blank=True, write_only=True, max_length=3
    )
    branch = serializers.PrimaryKeyRelatedField(
        queryset=LegalEntity.objects.none(), required=False, allow_null=True, write_only=True
    )
    # 3.3 section 4: opt-in, off by default (unlike the vehicle-asset
    # case) — same flag PartySerializer already supports.
    create_linked_cost_center = serializers.BooleanField(required=False, default=False, write_only=True)

    class Meta:
        model = Party
        fields = _PARTY_BASE_FIELDS + (
            "hire_date", "job_title", "direct_manager", "salary_currency",
            "branch", "create_linked_cost_center",
        )
        read_only_fields = _PARTY_BASE_READ_ONLY

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            self.fields["branch"].queryset = LegalEntity.objects.filter(tenant=request.user.tenant)

    def validate(self, attrs):
        _reject_roles_field(self.initial_data)
        return attrs

    def _pop_details_and_branch(self, validated_data, *, branch_provided):
        details = {
            "hire_date": str(validated_data.pop("hire_date", None) or "") or None,
            "job_title": validated_data.pop("job_title", "") or None,
            "direct_manager": validated_data.pop("direct_manager", "") or None,
            "salary_currency": validated_data.pop("salary_currency", "") or None,
        }
        branch = validated_data.pop("branch", _NOT_PROVIDED) if branch_provided else _NOT_PROVIDED
        return details, branch

    @transaction.atomic
    def create(self, validated_data):
        create_linked = validated_data.pop("create_linked_cost_center", False)
        details, branch = self._pop_details_and_branch(validated_data, branch_provided=True)
        branch = None if branch is _NOT_PROVIDED else branch
        tenant = validated_data["tenant"]
        party = Party.objects.create(
            code=generate_party_code(tenant, PartyRole.Role.EMPLOYEE), **validated_data
        )
        PartyRole.objects.create(
            party=party, role=PartyRole.Role.EMPLOYEE, details=details, legal_entity=branch
        )
        if create_linked:
            link_employee_cost_center(party)
        return party

    @transaction.atomic
    def update(self, instance, validated_data):
        validated_data.pop("create_linked_cost_center", None)  # only meaningful at creation
        branch_provided = "branch" in validated_data
        details, branch = self._pop_details_and_branch(validated_data, branch_provided=branch_provided)
        instance = super().update(instance, validated_data)
        role = instance.roles.get(role=PartyRole.Role.EMPLOYEE)
        role.details = {**role.details, **details}
        update_fields = ["details"]
        if branch is not _NOT_PROVIDED:
            role.legal_entity = branch
            update_fields.append("legal_entity")
        role.save(update_fields=update_fields)
        return instance

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        role = instance.roles.filter(role=PartyRole.Role.EMPLOYEE).first()
        details = role.details if role else {}
        rep["hire_date"] = details.get("hire_date")
        rep["job_title"] = details.get("job_title")
        rep["direct_manager"] = details.get("direct_manager")
        rep["salary_currency"] = details.get("salary_currency")
        rep["branch"] = role.legal_entity_id if role else None
        return rep


class AffiliatePartySerializer(serializers.ModelSerializer):
    """Backs `/api/parties/affiliates/`. `legal_entity` here is the
    matching node in the legal tree — required, not optional (3.3:
    "الكيان القانوني المقابل")."""

    roles = PartyRoleSerializer(many=True, read_only=True)
    legal_entity = serializers.PrimaryKeyRelatedField(
        queryset=LegalEntity.objects.none(), write_only=True
    )

    class Meta:
        model = Party
        fields = _PARTY_BASE_FIELDS + ("legal_entity",)
        read_only_fields = _PARTY_BASE_READ_ONLY

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            self.fields["legal_entity"].queryset = LegalEntity.objects.filter(
                tenant=request.user.tenant
            )

    def validate(self, attrs):
        _reject_roles_field(self.initial_data)
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        legal_entity = validated_data.pop("legal_entity")
        tenant = validated_data["tenant"]
        party = Party.objects.create(
            code=generate_party_code(tenant, PartyRole.Role.AFFILIATE), **validated_data
        )
        PartyRole.objects.create(party=party, role=PartyRole.Role.AFFILIATE, legal_entity=legal_entity)
        return party

    @transaction.atomic
    def update(self, instance, validated_data):
        legal_entity = validated_data.pop("legal_entity", _NOT_PROVIDED)
        instance = super().update(instance, validated_data)
        if legal_entity is not _NOT_PROVIDED:
            instance.roles.filter(role=PartyRole.Role.AFFILIATE).update(legal_entity=legal_entity)
        return instance

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        role = instance.roles.filter(role=PartyRole.Role.AFFILIATE).first()
        rep["legal_entity"] = role.legal_entity_id if role else None
        return rep


class DuplicatePartyCheckSerializer(serializers.Serializer):
    """Query-param input for PartyViewSet.check_duplicate — at least one
    of the two identifying fields is required."""

    tax_number = serializers.CharField(required=False, allow_blank=True, default="")
    national_id_or_cr = serializers.CharField(required=False, allow_blank=True, default="")
