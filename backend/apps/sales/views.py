from django.core.exceptions import PermissionDenied, ValidationError
from django.utils.translation import gettext_lazy as _
from rest_framework import filters
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.access.permissions import HasModulePermission
from apps.common.validators import future_date_warning
from apps.common.viewsets import (
    EntityScopedViewSet,
    SoftDeleteDocumentViewSetMixin,
    SoftDeleteViewSetMixin,
    TenantScopedViewSet,
)
from apps.tenants.services import TenantLimitExceeded, check_invoice_limit

from .models import Customer, Invoice, Product
from .serializers import (
    CustomerSerializer,
    InvoiceCreateSerializer,
    InvoiceSerializer,
    ProductSerializer,
    RejectInvoiceSerializer,
)
from .services import (
    VoidRejected,
    approve_invoice,
    credit_limit_check,
    import_items_csv,
    issue_invoice,
    reject_invoice,
    void_invoice,
    withdraw_invoice,
)


class CustomerViewSet(SoftDeleteViewSetMixin, TenantScopedViewSet):
    serializer_class = CustomerSerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = Customer.objects.all()
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "email", "phone"]
    ordering_fields = ["name", "created_at"]
    permission_map = {
        "list": "customers.view",
        "retrieve": "customers.view",
        "create": "customers.manage",
        "update": "customers.manage",
        "partial_update": "customers.manage",
        "destroy": "customers.manage",
        "deactivate": "customers.manage",
        "activate": "customers.manage",
    }


class ProductViewSet(SoftDeleteViewSetMixin, TenantScopedViewSet):
    serializer_class = ProductSerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = Product.objects.all()
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    # D9 (sprint 7.1): every item picker searches by code/name/barcode/
    # part number — "sku" is this project's own name for "code".
    search_fields = ["sku", "name", "barcodes__barcode", "part_number"]
    ordering_fields = ["name", "sku", "unit_price", "created_at"]
    permission_map = {
        "list": "products.view",
        "retrieve": "products.view",
        "create": "products.manage",
        "update": "products.manage",
        "partial_update": "products.manage",
        "destroy": "products.manage",
        "deactivate": "products.manage",
        "activate": "products.manage",
        "import_csv": "products.manage",
    }

    def get_queryset(self):
        # `barcodes__barcode` in search_fields above joins ItemBarcode —
        # a product with more than one barcode matching the search term
        # would otherwise come back once per matching barcode.
        qs = super().get_queryset()
        if self.action == "list":
            qs = qs.distinct()
            # 7.1 spec: the items screen filters by item_type/category/
            # tracking — plain query-param filtering (same pattern
            # ItemUoMViewSet/ItemBarcodeViewSet already use for `?item=`),
            # not DjangoFilterBackend, to avoid a new dependency for three
            # simple exact-match filters.
            item_type = self.request.query_params.get("item_type")
            if item_type:
                qs = qs.filter(item_type=item_type)
            category = self.request.query_params.get("category")
            if category:
                qs = qs.filter(category_id=category)
            tracking = self.request.query_params.get("tracking")
            if tracking:
                qs = qs.filter(tracking=tracking)
        return qs

    @action(detail=False, methods=["post"], parser_classes=[MultiPartParser, FormParser])
    def import_csv(self, request):
        """7.1 block spec, item 3: CSV import with a per-row Arabic
        error report — one bad row never aborts the others (see
        import_items_csv's own docstring)."""
        file_obj = request.FILES.get("file")
        if file_obj is None:
            return Response({"file": [_("ملف CSV مطلوب.")]}, status=400)
        created, errors = import_items_csv(request.user.tenant, file_obj)
        return Response({"created": created, "errors": errors})


class InvoiceViewSet(SoftDeleteDocumentViewSetMixin, EntityScopedViewSet):
    # Sprint 6.6.5: deliberately the mixin's own default ("draft" only)
    # — CANCELLED here only ever means `apps.sales.services.
    # void_invoice`, which requires the invoice to already be ISSUED
    # and posts a real reversal journal entry; a voided invoice has
    # genuine history and must never be deletable.

    queryset = Invoice.objects.select_related("party", "legal_entity").prefetch_related("lines", "lines__product")
    permission_classes = [IsAuthenticated, HasModulePermission]
    # PUT is deliberately excluded — PATCH (partial_update) is the only
    # write-after-create path, and it always requires the full `lines`
    # array anyway (same shape as create), so there's no reason for both.
    # DELETE re-included in 6.6.5 (unified delete rule) — soft delete
    # only, see SoftDeleteDocumentViewSetMixin above, never a real one.
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["number"]
    ordering_fields = ["issue_date", "number", "total", "created_at"]
    permission_map = {
        "list": "invoices.view",
        "retrieve": "invoices.view",
        "create": "invoices.create",
        "partial_update": "invoices.create",
        "issue": "invoices.approve",
        "approve": "invoices.approve",
        "reject": "invoices.approve",
        "void": "invoices.approve",
        "deliver": "invoices.view",
        "withdraw": "invoices.create",
        "destroy": "invoices.create",
    }

    def get_queryset(self):
        queryset = super().get_queryset().filter(tenant=self.request.user.tenant)
        # Sprint 3.5: backs the customer detail screen's "فواتيره" list
        # (docs/SYSTEM_ANALYSIS.md 3.18 rule 2).
        customer_id = self.request.query_params.get("customer")
        if customer_id:
            queryset = queryset.filter(party_id=customer_id)
        # Sprint 6.5.18 (UAT item 5): an explicit, OPTIONAL further
        # narrowing on top of accessible_ids above — never a silent
        # default. No `legal_entity` param means every accessible entity.
        legal_entity_id = self.request.query_params.get("legal_entity")
        if legal_entity_id:
            queryset = queryset.filter(legal_entity_id=legal_entity_id)
        return queryset

    def get_serializer_class(self):
        if self.action in ("create", "partial_update"):
            return InvoiceCreateSerializer
        return InvoiceSerializer

    def create(self, request, *args, **kwargs):
        try:
            check_invoice_limit(request.user.tenant)
        except TenantLimitExceeded as exc:
            return Response({"detail": exc.message}, status=402)
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        invoice = serializer.save()
        payload = InvoiceSerializer(invoice).data
        # Decision 16: always a warning at create time, regardless of
        # credit_limit_mode — BLOCK only ever applies at issue().
        credit_warning = credit_limit_check(invoice.tenant, invoice.party, invoice.base_total)
        payload["warnings"] = (
            future_date_warning(invoice.issue_date) + getattr(serializer, "rate_warnings", [])
            + ([credit_warning] if credit_warning else [])
        )
        return Response(payload, status=201)

    def partial_update(self, request, *args, **kwargs):
        # 3.13/rule 3: only a DRAFT invoice may be edited — once issued,
        # the only way to change it is void() below. CFO_REVIEW_1 C3:
        # 409 (not 400) — the request itself is well-formed, it's the
        # invoice's current state that conflicts with it; a
        # PENDING_APPROVAL invoice must use withdraw() first.
        invoice = self.get_object()
        if invoice.status != Invoice.Status.DRAFT:
            return Response(
                {"detail": _("Only draft invoices can be edited. Void it instead.")}, status=409
            )
        serializer = self.get_serializer(invoice, data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        invoice = serializer.save()
        payload = InvoiceSerializer(invoice).data
        payload["warnings"] = getattr(serializer, "rate_warnings", [])
        return Response(payload)

    @action(detail=True, methods=["post"])
    def issue(self, request, pk=None):
        invoice = self.get_object()
        credit_warning = credit_limit_check(invoice.tenant, invoice.party, invoice.base_total)
        features = getattr(invoice.tenant, "features", None)
        if credit_warning and features is not None and features.credit_limit_mode == "block":
            return Response({"detail": credit_warning}, status=400)
        try:
            invoice = issue_invoice(invoice, request.user, request=request)
        except (ValidationError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=400)
        payload = InvoiceSerializer(invoice).data
        payload["warnings"] = [credit_warning] if credit_warning else []
        return Response(payload)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        invoice = self.get_object()
        try:
            invoice = approve_invoice(
                invoice, request.user, request=request,
                emergency_reason=request.data.get("emergency_reason", ""),
            )
        except (ValidationError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=400)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=403)
        return Response(InvoiceSerializer(invoice).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        invoice = self.get_object()
        serializer = RejectInvoiceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            invoice = reject_invoice(invoice, request.user, serializer.validated_data["reason"], request=request)
        except (ValidationError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(InvoiceSerializer(invoice).data)

    @action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        invoice = self.get_object()
        try:
            invoice = withdraw_invoice(invoice, request.user, request=request)
        except (ValidationError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=400)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=403)
        return Response(InvoiceSerializer(invoice).data)

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        invoice = self.get_object()
        try:
            void_invoice(invoice, request.user, reason=request.data.get("reason", ""), request=request)
        except VoidRejected as exc:
            return Response({"detail": str(exc)}, status=409)
        except (ValidationError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(InvoiceSerializer(invoice).data)

    @action(detail=True, methods=["post"])
    def deliver(self, request, pk=None):
        """Sprint 5.6 (block 5.6, print page) — called once, fire-and-
        forget, the first time the invoice's print page loads. Set-once:
        a second print never overwrites the original delivery moment."""
        from django.utils import timezone

        invoice = self.get_object()
        if invoice.delivered_at is None:
            invoice.delivered_at = timezone.now()
            invoice.save(update_fields=["delivered_at"])
        return Response(InvoiceSerializer(invoice).data)
