from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.access.permissions import HasModulePermission
from apps.common.viewsets import TenantScopedViewSet
from apps.organization.services import get_accessible_entity_ids

from .models import Customer, Invoice, Product
from .serializers import (
    CustomerSerializer,
    InvoiceCreateSerializer,
    InvoiceIssueSerializer,
    InvoiceSerializer,
    ProductSerializer,
)


class CustomerViewSet(TenantScopedViewSet):
    serializer_class = CustomerSerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = Customer.objects.all()
    permission_map = {
        "list": "customers.view",
        "retrieve": "customers.view",
        "create": "customers.manage",
        "update": "customers.manage",
        "partial_update": "customers.manage",
        "destroy": "customers.manage",
    }


class ProductViewSet(TenantScopedViewSet):
    serializer_class = ProductSerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = Product.objects.all()
    permission_map = {
        "list": "products.view",
        "retrieve": "products.view",
        "create": "products.manage",
        "update": "products.manage",
        "partial_update": "products.manage",
        "destroy": "products.manage",
    }


class InvoiceViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasModulePermission]
    http_method_names = ["get", "post", "head", "options"]
    permission_map = {
        "list": "invoices.view",
        "retrieve": "invoices.view",
        "create": "invoices.create",
        "issue": "invoices.approve",
    }

    def get_queryset(self):
        accessible_ids = get_accessible_entity_ids(self.request.user)
        return (
            Invoice.objects.filter(tenant=self.request.user.tenant, legal_entity_id__in=accessible_ids)
            .select_related("customer", "legal_entity")
            .prefetch_related("lines", "lines__product")
        )

    def get_serializer_class(self):
        if self.action == "create":
            return InvoiceCreateSerializer
        return InvoiceSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        invoice = serializer.save()
        return Response(InvoiceSerializer(invoice).data, status=201)

    @action(detail=True, methods=["post"])
    def issue(self, request, pk=None):
        invoice = self.get_object()
        serializer = InvoiceIssueSerializer()
        invoice = serializer.save(invoice)
        return Response(InvoiceSerializer(invoice).data)
