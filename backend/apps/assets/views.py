from django.core.exceptions import PermissionDenied, ValidationError
from django.utils.translation import gettext_lazy as _
from rest_framework import filters, mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.access.permissions import HasModulePermission
from apps.accounting.models import RecurringEntry
from apps.accounting.serializers import OpeningBalanceReasonSerializer, RecurringEntrySerializer
from apps.common.viewsets import SoftDeleteViewSetMixin, TenantScopedViewSet

from .depreciation import DepreciationAlreadyActive, NoActiveDepreciationSchedule
from .depreciation import add_to_asset as _add_to_asset
from .depreciation import approve_depreciation_schedule as _approve_depreciation_schedule
from .depreciation import reject_depreciation_schedule as _reject_depreciation_schedule
from .depreciation import start_depreciation as _start_depreciation
from .depreciation import withdraw_depreciation_schedule as _withdraw_depreciation_schedule
from .disposal import approve_disposal as _approve_disposal
from .disposal import dispose_asset as _dispose_asset
from .disposal import reject_disposal as _reject_disposal
from .disposal import withdraw_disposal as _withdraw_disposal
from .models import Asset, AssetDisposal
from .serializers import (
    AssetAdditionCreateSerializer,
    AssetAdditionSerializer,
    AssetDisposalSerializer,
    AssetDisposeCreateSerializer,
    AssetSerializer,
)


class AssetViewSet(SoftDeleteViewSetMixin, TenantScopedViewSet):
    serializer_class = AssetSerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = Asset.objects.all()
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["code", "name"]
    ordering_fields = ["code", "name", "purchase_date", "created_at"]
    permission_map = {
        "list": "assets.view",
        "retrieve": "assets.view",
        "create": "assets.manage",
        "update": "assets.manage",
        "partial_update": "assets.manage",
        "destroy": "assets.manage",
        "deactivate": "assets.manage",
        "activate": "assets.manage",
        # Sprint 6.5 (decision 15): starting/adding to/disposing of a
        # depreciation schedule is a separate authority from editing
        # the plain registry row (assets.manage).
        "start_depreciation": "assets.depreciate",
        "additions": "assets.depreciate",
        "dispose": "assets.depreciate",
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        # Sprint 3.5: backs the employee detail screen's "أصوله المحفوظة
        # عنده" list.
        custodian_id = self.request.query_params.get("custodian")
        if custodian_id:
            queryset = queryset.filter(custodian_id=custodian_id)
        return queryset

    @action(detail=True, methods=["post"], url_path="start-depreciation")
    def start_depreciation(self, request, pk=None):
        asset = self.get_object()
        try:
            entry, warnings = _start_depreciation(asset, request.user, request=request)
        except DepreciationAlreadyActive as exc:
            return Response({"detail": str(exc)}, status=409)
        except (ValidationError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=400)
        asset.refresh_from_db()
        data = AssetSerializer(asset, context={"request": request}).data
        data["warnings"] = warnings
        data["depreciation_schedule_id"] = str(entry.id)
        return Response(data, status=201)

    @action(detail=True, methods=["post"])
    def additions(self, request, pk=None):
        asset = self.get_object()
        serializer = AssetAdditionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            addition = _add_to_asset(
                asset, request.user, date=data["date"], amount_base=data["amount_base"],
                description=data["description"], extend_life_months=data["extend_life_months"], request=request,
            )
        except NoActiveDepreciationSchedule as exc:
            return Response({"detail": str(exc)}, status=409)
        except (ValidationError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(AssetAdditionSerializer(addition).data, status=201)

    @action(detail=True, methods=["post"])
    def dispose(self, request, pk=None):
        asset = self.get_object()
        serializer = AssetDisposeCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            disposal = _dispose_asset(
                asset, request.user, date=data["date"], fraction=data["fraction"],
                proceeds_base=data["proceeds_base"], proceeds_account=data["proceeds_account"],
                proceeds_party=data["proceeds_party"], proceeds_party_role=data["proceeds_party_role"],
                reason=data["reason"], request=request,
            )
        except (ValidationError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=400)
        payload = AssetDisposalSerializer(disposal).data
        if disposal.proceeds_base > 0:
            payload["warnings"] = [
                str(
                    _("بيع الأصل يستوجب فاتورة ضريبية للمشتري — أصدرها يدويًا حتى سبرنت 9.")
                )
            ]
        return Response(payload, status=201)


class DepreciationScheduleViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Sprint 6.5.1 (decision 11): the ASSET_DEPRECIATION approval
    channel's own endpoint — same generic-inbox dispatch pattern
    apps.accounting.views.RecurringEntryViewSet already uses for
    "recurring_entry" (apps.approvals.services.list_pending_approvals
    /the frontend inbox both call `/{path}/{id}/approve/` generically),
    scoped to kind=DEPRECIATION schedules only. The underlying row is
    still a plain RecurringEntry — reused as-is, never a separate model."""

    serializer_class = RecurringEntrySerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    permission_map = {
        "retrieve": "assets.view",
        "approve": "assets.depreciate",
        "reject": "assets.depreciate",
        "withdraw": "assets.depreciate",
    }

    def get_queryset(self):
        return RecurringEntry.objects.filter(
            tenant=self.request.user.tenant, kind=RecurringEntry.Kind.DEPRECIATION
        ).select_related("legal_entity", "from_account", "to_account").prefetch_related("installments")

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        entry = self.get_object()
        try:
            _approve_depreciation_schedule(
                entry, request.user, request=request, emergency_reason=request.data.get("emergency_reason", ""),
            )
        except (ValidationError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=400)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=403)
        entry.refresh_from_db()
        return Response(RecurringEntrySerializer(entry).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        entry = self.get_object()
        serializer = OpeningBalanceReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            _reject_depreciation_schedule(entry, request.user, serializer.validated_data["reason"], request=request)
        except (ValidationError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(RecurringEntrySerializer(entry).data)

    @action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        entry = self.get_object()
        try:
            _withdraw_depreciation_schedule(entry, request.user, request=request)
        except (ValidationError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=400)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=403)
        return Response(RecurringEntrySerializer(entry).data)


class AssetDisposalViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Sprint 6.5.4 (decision 11): the ASSET_DISPOSAL approval
    channel's own endpoint — same generic-inbox dispatch pattern as
    DepreciationScheduleViewSet above, but the underlying document is
    its own AssetDisposal model (unlike start/addition, a disposal is
    never itself a RecurringEntry)."""

    serializer_class = AssetDisposalSerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    permission_map = {
        "retrieve": "assets.view",
        "approve": "assets.depreciate",
        "reject": "assets.depreciate",
        "withdraw": "assets.depreciate",
    }

    def get_queryset(self):
        return AssetDisposal.objects.filter(tenant=self.request.user.tenant).select_related("asset")

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        disposal = self.get_object()
        try:
            _approve_disposal(
                disposal, request.user, request=request, emergency_reason=request.data.get("emergency_reason", ""),
            )
        except (ValidationError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=400)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=403)
        disposal.refresh_from_db()
        return Response(AssetDisposalSerializer(disposal).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        disposal = self.get_object()
        serializer = OpeningBalanceReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            _reject_disposal(disposal, request.user, serializer.validated_data["reason"], request=request)
        except (ValidationError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(AssetDisposalSerializer(disposal).data)

    @action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        disposal = self.get_object()
        try:
            _withdraw_disposal(disposal, request.user, request=request)
        except (ValidationError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=400)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=403)
        return Response(AssetDisposalSerializer(disposal).data)
