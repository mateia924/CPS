from django.utils.translation import gettext_lazy as _
from rest_framework import filters
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.access.permissions import HasModulePermission
from apps.common.viewsets import SoftDeleteViewSetMixin, TenantScopedViewSet

from .models import Party, PartyRole
from .serializers import PartyRoleInputSerializer, PartySerializer
from .services import link_employee_cost_center


class PartyViewSet(SoftDeleteViewSetMixin, TenantScopedViewSet):
    """Backs the unified "الأطراف" screen (3.3) — one resource, filtered
    by role for each tab via `?role=`."""

    serializer_class = PartySerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = Party.objects.all().prefetch_related("roles")
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
        "add_role": "parties.manage",
    }

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
        if role == PartyRole.Role.EMPLOYEE and serializer.validated_data.get("create_linked_cost_center"):
            link_employee_cost_center(party)
        # `party` was fetched via get_object() through a queryset with
        # prefetch_related("roles") — without this, PartySerializer
        # below would serialize the *cached* (now stale) roles list,
        # missing the role just created above.
        party.refresh_from_db()
        return Response(PartySerializer(party, context={"request": request}).data, status=201)
