from decimal import Decimal

from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.accounting.models import Account, TaxCode
from apps.common.constants import RATE_DECIMAL_PLACES, RATE_MAX_DIGITS
from apps.inventory.models import InventorySettings, ItemCategory, UnitOfMeasure
from apps.organization.models import CostCenter, LegalEntity
from apps.organization.services import default_branch_for_tenant, get_accessible_entity_ids
from apps.parties.models import Party, PartyRole
from apps.platform.models import AuditLog
from apps.platform.services import log_action
from apps.treasury.services import ExchangeRateNotFound, get_rate_with_warnings

from .models import Customer, Invoice, InvoiceLine, Product
from .services import create_invoice, update_invoice


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ("id", "name", "email", "phone", "tax_number", "address", "is_active", "created_at")
        read_only_fields = ("id", "created_at")


class ProductSerializer(serializers.ModelSerializer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            tenant = request.user.tenant
            self.fields["default_tax_code"].queryset = TaxCode.objects.filter(
                tenant=tenant, is_active=True
            )
            self.fields["category"].queryset = ItemCategory.objects.filter(tenant=tenant, is_active=True)
            self.fields["base_uom"].queryset = UnitOfMeasure.objects.filter(tenant=tenant)
            self.fields["parent"].queryset = Product.objects.filter(tenant=tenant, is_template=True)
            self.fields["inventory_account_override"].queryset = Account.objects.filter(
                tenant=tenant, is_active=True
            )
            self.fields["cogs_account_override"].queryset = Account.objects.filter(
                tenant=tenant, is_active=True
            )

    class Meta:
        model = Product
        fields = (
            "id", "sku", "name", "unit_price", "tax_rate", "default_tax_code", "is_active", "created_at",
            "item_type", "category", "base_uom", "tracking", "expiry_required", "reorder_level",
            "is_bundle", "pricing_mode", "parent", "is_template", "metal", "karat", "weight_grams",
            "making_charge_per_gram", "part_number", "purchase_cost_default",
            "inventory_account_override", "cogs_account_override",
        )
        read_only_fields = ("id", "created_at")

    def validate(self, attrs):
        item_type = attrs.get("item_type", getattr(self.instance, "item_type", Product.ItemType.SERVICE))
        tracking = attrs.get("tracking", getattr(self.instance, "tracking", ""))
        # 7.1 test item 3: a service item never accepts real tracking
        # (serial/batch) — "" and NONE both mean "not tracked" and stay
        # allowed, same distinction as Product.clean()'s own check.
        if item_type == Product.ItemType.SERVICE and tracking in (
            InventorySettings.Tracking.SERIAL, InventorySettings.Tracking.BATCH,
        ):
            raise serializers.ValidationError(
                {"tracking": [_("A service item cannot have tracking (serial/batch).")]}
            )
        # 7.1 test item 4: changing the base unit for an item that
        # already has real movements is refused. StockDocumentLine
        # (D5) doesn't exist until sprint 7.2/7.3 — invoice_lines is
        # the only "movement" that can exist on a Product today; this
        # check extends to StockDocumentLine once that model lands.
        if (
            self.instance is not None
            and "base_uom" in attrs
            and attrs["base_uom"] != self.instance.base_uom
            and self.instance.invoice_lines.exists()
        ):
            raise serializers.ValidationError(
                {"base_uom": [_("Cannot change the base unit of an item that already has movements.")]}
            )
        return attrs


class InvoiceLineSerializer(serializers.ModelSerializer):
    tax_code_display = serializers.CharField(source="tax_code.code", read_only=True)

    class Meta:
        model = InvoiceLine
        fields = (
            "id", "product", "cost_center", "tax_code", "tax_code_display", "description",
            "quantity", "unit_price", "tax_rate", "line_subtotal", "line_tax", "line_total",
        )
        read_only_fields = fields


class InvoiceSerializer(serializers.ModelSerializer):
    lines = InvoiceLineSerializer(many=True, read_only=True)
    # Sprint 3 (3.3): the underlying model field is `party` (FK to
    # parties.Party, role=CUSTOMER) — the API keeps the "customer" name
    # for continuity with the existing invoice screens/tests, since
    # conceptually it's still "who this invoice is billed to".
    customer = serializers.PrimaryKeyRelatedField(source="party", read_only=True)
    customer_name = serializers.CharField(source="party.name", read_only=True)
    # Sprint 5.6 (print page): "فاتورة ضريبية" لعميل منشأة / "فاتورة
    # ضريبية مبسّطة" لعميل فرد — القرار يعتمد على نوع الطرف لا الحالة.
    customer_party_type = serializers.CharField(source="party.party_type", read_only=True)
    legal_entity_name = serializers.CharField(source="legal_entity.name", read_only=True)
    # Sprint 6 (block 6.0, item 1): server-side label alongside the raw
    # `status` value — reads Django's own translation catalog
    # (locale/ar), so it renders correctly wherever Accept-Language is
    # honored (server-rendered contexts like the approval digest email,
    # not just the frontend's own i18n dictionary).
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    # Sprint 6 (block 6.0, item 2): the journal entry this invoice
    # generated, as a link target on the detail screen — resolved via
    # the same GenericFK every system-generated JournalEntry already
    # carries (source_type='invoice'), not a new FK column.
    journal_entry_id = serializers.SerializerMethodField()
    journal_entry_number = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = (
            "id", "number", "status", "status_label", "created_by", "issue_date", "due_date", "customer",
            "customer_name", "customer_party_type",
            "legal_entity", "legal_entity_name", "currency", "exchange_rate",
            "subtotal", "tax_total", "total", "base_total", "paid_fc", "balance_fc", "payment_status",
            "delivered_at", "is_post_delivery_void", "journal_entry_id", "journal_entry_number", "lines",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "number", "status", "status_label", "created_by", "due_date", "customer_name",
            "customer_party_type",
            "legal_entity_name", "currency", "exchange_rate", "subtotal", "tax_total", "total", "base_total",
            "paid_fc", "balance_fc", "payment_status", "delivered_at", "is_post_delivery_void",
            "journal_entry_id", "journal_entry_number", "lines", "created_at", "updated_at",
        )

    def _journal_entry(self, obj):
        from django.contrib.contenttypes.models import ContentType

        from apps.accounting.models import JournalEntry

        if not hasattr(obj, "_cached_journal_entry"):
            obj._cached_journal_entry = JournalEntry.objects.filter(
                tenant_id=obj.tenant_id, content_type=ContentType.objects.get_for_model(Invoice),
                object_id=obj.id, source_type="invoice",
            ).first()
        return obj._cached_journal_entry

    def get_journal_entry_id(self, obj):
        entry = self._journal_entry(obj)
        return str(entry.id) if entry else None

    def get_journal_entry_number(self, obj):
        entry = self._journal_entry(obj)
        return entry.number if entry else None


class InvoiceLineInputSerializer(serializers.Serializer):
    # `product`/`cost_center` are bare UUIDs here, not
    # PrimaryKeyRelatedFields: that field type is declared once at
    # class-definition time (this serializer is nested as
    # `InvoiceCreateSerializer.lines`), long before any request context
    # exists, so a queryset scoped to request.user.tenant can't be bound
    # to it per-request. Tenant scoping is enforced explicitly in
    # InvoiceCreateSerializer.create() instead, which resolves each id
    # against the caller's tenant.
    product = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    # Optional, line-level (docs/SYSTEM_ANALYSIS.md 3.2/3.3) — never
    # required, never on the document.
    cost_center = serializers.UUIDField(required=False, allow_null=True)
    # Sprint 4.6 (3.16.2, rule 16): mandatory — a line with no tax_code
    # is rejected (400), by this field simply being required.
    tax_code = serializers.UUIDField()


class InvoiceCreateSerializer(serializers.Serializer):
    # Sprint 3 (3.3): "في الفاتورة: اختيار العميل من الأطراف بدور
    # CUSTOMER فقط" — the queryset below (set per-request in __init__)
    # only offers parties holding an active CUSTOMER role, so a party
    # without that role 400s exactly like any other invalid id, same as
    # picking another tenant's party.
    customer = serializers.PrimaryKeyRelatedField(source="party", queryset=Party.objects.none())
    # Mandatory (rule 3) but may be omitted by the client when the
    # tenant is in simplified mode (3.13) — auto-filled server-side with
    # the tenant's single branch in that case; see validate() below.
    legal_entity = serializers.PrimaryKeyRelatedField(
        queryset=LegalEntity.objects.none(), required=False
    )
    issue_date = serializers.DateField(required=False)
    # Sprint 4.2 (3.11/3.15.3): both optional. currency defaults to the
    # invoice's legal_entity's base currency (the common, single-
    # currency case for most small clients never needs either field);
    # exchange_rate, if omitted, is auto-pulled from ExchangeRate by
    # issue_date — see validate() below, which is where both actually
    # get resolved (legal_entity/issue_date must already be resolved
    # first).
    currency = serializers.CharField(max_length=3, required=False)
    exchange_rate = serializers.DecimalField(
        max_digits=RATE_MAX_DIGITS, decimal_places=RATE_DECIMAL_PLACES, required=False
    )
    lines = InvoiceLineInputSerializer(many=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            tenant = request.user.tenant
            self.fields["customer"].queryset = Party.objects.filter(
                tenant=tenant, roles__role=PartyRole.Role.CUSTOMER, roles__is_active=True
            )
            accessible_ids = get_accessible_entity_ids(request.user)
            self.fields["legal_entity"].queryset = LegalEntity.objects.filter(
                tenant=tenant, id__in=accessible_ids
            )

    def validate_lines(self, value):
        if not value:
            raise serializers.ValidationError(_("At least one invoice line is required."))
        return value

    def validate(self, attrs):
        if "legal_entity" not in attrs:
            tenant = self.context["request"].user.tenant
            default_branch = default_branch_for_tenant(tenant)
            if default_branch is None:
                raise serializers.ValidationError(
                    {"legal_entity": [_("This field is required.")]}
                )
            attrs["legal_entity"] = default_branch

        legal_entity = attrs["legal_entity"]
        currency = attrs.get("currency") or legal_entity.base_currency
        attrs["currency"] = currency
        issue_date = attrs.get("issue_date") or timezone.localdate()
        attrs["issue_date"] = issue_date

        # Sprint 6.1 (decision 3): checked at save time too (even a
        # DRAFT), not just at issuance — assert_open_period is the one
        # gate every document date clears before it's ever written.
        from django.core.exceptions import ValidationError as DjangoValidationError

        from apps.accounting.periods import assert_open_period

        tenant = self.context["request"].user.tenant
        try:
            assert_open_period(tenant, issue_date)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"issue_date": [str(exc.message)]})

        # Sprint 6 (block 6.0, item 6): surfaced to the view via
        # self.rate_warnings — a stale rate (>7 days old, CFO_REVIEW_1
        # C14) is a warning, never a block, same as vouchers (5.7).
        self.rate_warnings = []
        if currency == legal_entity.base_currency:
            # Same currency is always rate 1 — an explicit override
            # here would be meaningless, so it's ignored rather than
            # honored (never silently wrong money, just a no-op field).
            attrs["exchange_rate"] = Decimal("1")
            attrs["_rate_overridden"] = False
        elif "exchange_rate" in attrs:
            attrs["_rate_overridden"] = True
        else:
            tenant = self.context["request"].user.tenant
            try:
                attrs["exchange_rate"], self.rate_warnings = get_rate_with_warnings(
                    tenant, currency, legal_entity.base_currency, issue_date
                )
            except ExchangeRateNotFound as exc:
                raise serializers.ValidationError({"exchange_rate": [str(exc.message)]})
            attrs["_rate_overridden"] = False

        return attrs

    def _log_rate_override_if_needed(self, invoice, attrs):
        if not attrs.pop("_rate_overridden", False):
            return
        request = self.context["request"]
        log_action(
            actor_type=AuditLog.ActorType.TENANT_USER,
            actor_id=request.user.id,
            action="invoice.exchange_rate_overridden",
            target_type="invoice",
            target_id=invoice.id,
            tenant_id=request.user.tenant_id,
            after={"currency": invoice.currency, "exchange_rate": str(invoice.exchange_rate)},
            request=request,
        )

    def _resolve_lines(self, tenant, raw_lines):
        resolved = []
        for line in raw_lines:
            try:
                product = Product.objects.get(
                    tenant=tenant, id=line["product"], is_active=True
                )
            except Product.DoesNotExist:
                raise serializers.ValidationError(
                    {"lines": [_("Product not found.")]}
                )
            cost_center = None
            cost_center_id = line.get("cost_center")
            if cost_center_id:
                try:
                    cost_center = CostCenter.objects.get(tenant=tenant, id=cost_center_id)
                except CostCenter.DoesNotExist:
                    raise serializers.ValidationError(
                        {"lines": [_("Cost center not found.")]}
                    )
            # Sprint 6.8 (D5, decision 19): every invoice line posts to
            # a revenue account by construction — no per-line account
            # type check needed, unlike the manual-JV/voucher case.
            # TenantFeatures may not exist yet (only RegisterSerializer
            # creates it) — treat that the same as "not enabled".
            features = getattr(tenant, "features", None)
            if cost_center is None and features is not None and features.cost_center_required:
                raise serializers.ValidationError(
                    {"lines": [_("سطر الفاتورة يتطلب مركز تكلفة.")]}
                )
            try:
                tax_code = TaxCode.objects.get(tenant=tenant, id=line["tax_code"], is_active=True)
            except TaxCode.DoesNotExist:
                raise serializers.ValidationError({"lines": [_("Tax code not found.")]})
            resolved.append(
                {
                    "product": product, "quantity": line["quantity"], "cost_center": cost_center,
                    "tax_code": tax_code,
                }
            )
        return resolved

    def create(self, validated_data):
        request = self.context["request"]
        tenant = request.user.tenant
        resolved_lines = self._resolve_lines(tenant, validated_data["lines"])
        invoice = create_invoice(
            tenant=tenant,
            party=validated_data["party"],
            legal_entity=validated_data["legal_entity"],
            issue_date=validated_data.get("issue_date") or timezone.localdate(),
            line_inputs=resolved_lines,
            currency=validated_data["currency"],
            exchange_rate=validated_data["exchange_rate"],
            created_by=request.user,
        )
        self._log_rate_override_if_needed(invoice, validated_data)
        return invoice

    def update(self, instance, validated_data):
        tenant = self.context["request"].user.tenant
        resolved_lines = self._resolve_lines(tenant, validated_data["lines"])
        invoice = update_invoice(
            instance,
            party=validated_data["party"],
            legal_entity=validated_data["legal_entity"],
            issue_date=validated_data.get("issue_date") or instance.issue_date,
            line_inputs=resolved_lines,
            currency=validated_data["currency"],
            exchange_rate=validated_data["exchange_rate"],
        )
        self._log_rate_override_if_needed(invoice, validated_data)
        return invoice


class RejectInvoiceSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=3)
