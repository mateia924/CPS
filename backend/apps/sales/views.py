from django.core.exceptions import PermissionDenied, ValidationError
from django.utils.translation import gettext_lazy as _
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.access.permissions import HasModulePermission
from apps.accounting.services import void_invoice_journal_entry
from apps.common.validators import future_date_warning
from apps.common.viewsets import SoftDeleteViewSetMixin, TenantScopedViewSet
from apps.organization.services import get_accessible_entity_ids
from apps.platform.models import AuditLog
from apps.platform.services import log_action
from apps.tenants.services import TenantLimitExceeded, check_invoice_limit

from .models import Customer, Invoice, Product
from .serializers import (
    CustomerSerializer,
    InvoiceCreateSerializer,
    InvoiceSerializer,
    ProductSerializer,
    RejectInvoiceSerializer,
)
from .services import approve_invoice, issue_invoice, reject_invoice, withdraw_invoice


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
    search_fields = ["sku", "name"]
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
    }


class InvoiceViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasModulePermission]
    # PUT is deliberately excluded — PATCH (partial_update) is the only
    # write-after-create path, and it always requires the full `lines`
    # array anyway (same shape as create), so there's no reason for both.
    http_method_names = ["get", "post", "patch", "head", "options"]
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
    }

    def get_queryset(self):
        accessible_ids = get_accessible_entity_ids(self.request.user)
        queryset = (
            Invoice.objects.filter(tenant=self.request.user.tenant, legal_entity_id__in=accessible_ids)
            .select_related("party", "legal_entity")
            .prefetch_related("lines", "lines__product")
        )
        # Sprint 3.5: backs the customer detail screen's "فواتيره" list
        # (docs/SYSTEM_ANALYSIS.md 3.18 rule 2).
        customer_id = self.request.query_params.get("customer")
        if customer_id:
            queryset = queryset.filter(party_id=customer_id)
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
        payload["warnings"] = future_date_warning(invoice.issue_date) + getattr(serializer, "rate_warnings", [])
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
        try:
            invoice = issue_invoice(invoice, request.user, request=request)
        except (ValidationError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(InvoiceSerializer(invoice).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        invoice = self.get_object()
        try:
            invoice = approve_invoice(invoice, request.user, request=request)
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
        if invoice.status != Invoice.Status.ISSUED:
            return Response(
                {"detail": _("Only issued invoices can be voided.")}, status=400
            )
        invoice.status = Invoice.Status.CANCELLED
        invoice.save(update_fields=["status"])
        void_invoice_journal_entry(invoice)
        log_action(
            actor_type=AuditLog.ActorType.TENANT_USER,
            actor_id=request.user.id,
            action="invoice.void",
            target_type="sales.Invoice",
            target_id=invoice.id,
            tenant_id=request.user.tenant_id,
            after={"number": invoice.number},
            request=request,
        )
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
