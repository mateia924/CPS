from django.utils.translation import gettext_lazy as _
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.access.permissions import HasModulePermission
from apps.accounting.services import void_invoice_journal_entry
from apps.common.viewsets import SoftDeleteViewSetMixin, TenantScopedViewSet
from apps.organization.services import get_accessible_entity_ids

from .models import Customer, Invoice, Product
from .serializers import (
    CustomerSerializer,
    InvoiceCreateSerializer,
    InvoiceIssueSerializer,
    InvoiceSerializer,
    ProductSerializer,
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
        "void": "invoices.approve",
    }

    def get_queryset(self):
        accessible_ids = get_accessible_entity_ids(self.request.user)
        return (
            Invoice.objects.filter(tenant=self.request.user.tenant, legal_entity_id__in=accessible_ids)
            .select_related("customer", "legal_entity")
            .prefetch_related("lines", "lines__product")
        )

    def get_serializer_class(self):
        if self.action in ("create", "partial_update"):
            return InvoiceCreateSerializer
        return InvoiceSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        invoice = serializer.save()
        return Response(InvoiceSerializer(invoice).data, status=201)

    def partial_update(self, request, *args, **kwargs):
        # 3.13/rule 3: only a DRAFT invoice may be edited — once issued,
        # the only way to change it is void() below.
        invoice = self.get_object()
        if invoice.status != Invoice.Status.DRAFT:
            return Response(
                {"detail": _("Only draft invoices can be edited. Void it instead.")}, status=400
            )
        serializer = self.get_serializer(invoice, data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        invoice = serializer.save()
        return Response(InvoiceSerializer(invoice).data)

    @action(detail=True, methods=["post"])
    def issue(self, request, pk=None):
        invoice = self.get_object()
        serializer = InvoiceIssueSerializer()
        invoice = serializer.save(invoice)
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
        return Response(InvoiceSerializer(invoice).data)
