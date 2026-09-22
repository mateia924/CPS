from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from rest_framework import filters
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.access.permissions import HasModulePermission
from apps.accounting.services import get_or_create_party_role_account
from apps.common.viewsets import SoftDeleteViewSetMixin, TenantScopedViewSet

from .models import Party, PartyRole
from .serializers import (
    AffiliatePartySerializer,
    CustomerPartySerializer,
    DuplicatePartyCheckSerializer,
    EmployeePartySerializer,
    PartyRoleInputSerializer,
    PartySerializer,
    SupplierPartySerializer,
)
from .services import link_employee_cost_center


class PartyViewSet(SoftDeleteViewSetMixin, TenantScopedViewSet):
    """Backs the "الأطراف (عرض شامل)" screen under Settings (3.3 v1.4) —
    moved there in sprint 3.5 after UAT rejected it as the primary
    customer/supplier/etc. screen (an accountant didn't recognize "طرف
    بدور عميل"). Now gated by `parties.view_all` (accounts managers
    only) for list/retrieve; the day-to-day screens are the dedicated
    ViewSets below instead."""

    serializer_class = PartySerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = Party.objects.all().prefetch_related("roles")
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["code", "name", "name_en", "phone", "email", "tax_number"]
    ordering_fields = ["name", "code", "created_at"]
    permission_map = {
        "list": "parties.view_all",
        "retrieve": "parties.view_all",
        "create": "parties.manage",
        "update": "parties.manage",
        "partial_update": "parties.manage",
        "destroy": "parties.manage",
        "deactivate": "parties.manage",
        "activate": "parties.manage",
        "add_role": "parties.manage",
        "check_duplicate": "parties.manage",
    }

    @action(detail=False, methods=["get"], url_path="check-duplicate")
    def check_duplicate(self, request):
        """3.3 v1.4 item 4 (sprint 3.5): the actual duplicate check lives
        here, in the backend — the dedicated Customer/Supplier/Employee/
        Affiliate screens call this before creating, so the confirmation
        dialog ("this party is already registered as X — add as Y too?")
        is never just a frontend guess."""
        params = DuplicatePartyCheckSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        tax_number = params.validated_data["tax_number"].strip()
        national_id_or_cr = params.validated_data["national_id_or_cr"].strip()
        if not tax_number and not national_id_or_cr:
            return Response({"party": None})

        query = Q()
        if tax_number:
            query |= Q(tax_number=tax_number)
        if national_id_or_cr:
            query |= Q(national_id_or_cr=national_id_or_cr)
        party = Party.objects.filter(tenant=request.user.tenant).filter(query).first()
        if party is None:
            return Response({"party": None})
        return Response({"party": PartySerializer(party, context={"request": request}).data})

    def get_queryset(self):
        queryset = super().get_queryset()
        role = self.request.query_params.get("role")
        if role:
            queryset = queryset.filter(roles__role=role, roles__is_active=True)
        return queryset

    @action(detail=True, methods=["post"], url_path="add-role")
    def add_role(self, request, pk=None):
        party = self.get_object()
        serializer = PartyRoleInputSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        role = serializer.validated_data["role"]
        if PartyRole.objects.filter(party=party, role=role).exists():
            return Response(
                {"detail": _("This party already has this role.")}, status=400
            )
        PartyRole.objects.create(
            party=party,
            role=role,
            details=serializer.validated_data.get("details", {}),
            legal_entity=serializer.validated_data.get("legal_entity"),
        )
        get_or_create_party_role_account(party, role)
        if role == PartyRole.Role.EMPLOYEE and serializer.validated_data.get("create_linked_cost_center"):
            link_employee_cost_center(party)
        # `party` was fetched via get_object() through a queryset with
        # prefetch_related("roles") — without this, PartySerializer
        # below would serialize the *cached* (now stale) roles list,
        # missing the role just created above.
        party.refresh_from_db()
        return Response(PartySerializer(party, context={"request": request}).data, status=201)


class _PartyByRoleViewSet(SoftDeleteViewSetMixin, TenantScopedViewSet):
    """Base for the sprint-3.5 accountant-facing screens: each is a
    thin, role-fixed view onto the same Party/PartyRole tables —
    `roles.view`/`manage` stay the operative permissions (already
    granted broadly, e.g. to Sales), since these are the ordinary
    day-to-day screens, not the gated advanced view above."""

    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = Party.objects.all()
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["code", "name", "name_en", "phone", "email", "tax_number"]
    ordering_fields = ["name", "code", "created_at"]
    permission_map = {
        "list": "parties.view",
        "retrieve": "parties.view",
        "create": "parties.manage",
        "update": "parties.manage",
        "partial_update": "parties.manage",
        "destroy": "parties.manage",
        "deactivate": "parties.manage",
        "activate": "parties.manage",
    }
    role_const = None

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(roles__role=self.role_const, roles__is_active=True)
            .prefetch_related("roles")
        )


class CustomerPartyViewSet(_PartyByRoleViewSet):
    """`/api/parties/customers/` — "العملاء" in the sidebar."""

    serializer_class = CustomerPartySerializer
    role_const = PartyRole.Role.CUSTOMER


class SupplierPartyViewSet(_PartyByRoleViewSet):
    """`/api/parties/suppliers/` — "الموردون" in the sidebar."""

    serializer_class = SupplierPartySerializer
    role_const = PartyRole.Role.SUPPLIER


class EmployeePartyViewSet(_PartyByRoleViewSet):
    """`/api/parties/employees/` — "الموظفون" in the sidebar."""

    serializer_class = EmployeePartySerializer
    role_const = PartyRole.Role.EMPLOYEE


class AffiliatePartyViewSet(_PartyByRoleViewSet):
    """`/api/parties/affiliates/` — "الشركات الشقيقة" in the sidebar."""

    serializer_class = AffiliatePartySerializer
    role_const = PartyRole.Role.AFFILIATE
