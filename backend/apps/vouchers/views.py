from django.core.exceptions import PermissionDenied, ValidationError
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.access.permissions import HasModulePermission
from apps.organization.services import get_accessible_entity_ids
from apps.treasury.services import ExchangeRateNotFound, TreasuryConflictError

from .models import Voucher
from .serializers import (
    InternalTransferCreateSerializer,
    RejectVoucherSerializer,
    VoucherCreateSerializer,
    VoucherSerializer,
    resolve_voucher_lines,
)
from .services import (
    VoucherValidationError,
    approve_voucher,
    create_internal_transfer_voucher,
    create_voucher,
    post_voucher,
    reject_voucher,
    reverse_voucher,
    withdraw_voucher,
)


class VoucherViewSet(
    mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """docs/SYSTEM_ANALYSIS.md 3.8 — سندات القبض/الصرف/التسوية، محرك
    واحد. `create` only ever builds a DRAFT; every transition after
    that is its own action, same shape as JournalEntryViewSet (4.4)."""

    serializer_class = VoucherSerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    permission_map = {
        "list": "vouchers.view",
        "retrieve": "vouchers.view",
        "create": "vouchers.add",
        "transfer": "vouchers.add",
        "post": "vouchers.post",
        "approve": "vouchers.approve",
        "reject": "vouchers.approve",
        "withdraw": "vouchers.add",
        "reverse": "vouchers.reverse",
    }

    def get_queryset(self):
        accessible_ids = get_accessible_entity_ids(self.request.user)
        queryset = Voucher.objects.filter(
            tenant=self.request.user.tenant, legal_entity_id__in=accessible_ids
        ).prefetch_related("lines")
        voucher_type = self.request.query_params.get("voucher_type")
        if voucher_type:
            queryset = queryset.filter(voucher_type=voucher_type)
        # Sprint 5.6: backs the customer/employee detail screen's
        # "السندات" tab (3.18 rule 2), same pattern as Invoice's own
        # ?customer= filter (sprint 3.5).
        party_id = self.request.query_params.get("party")
        if party_id:
            queryset = queryset.filter(party_id=party_id)
        return queryset

    def create(self, request, *args, **kwargs):
        serializer = VoucherCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        tenant = request.user.tenant
        try:
            resolved_lines = resolve_voucher_lines(tenant, data["lines"])
            voucher = create_voucher(
                tenant=tenant,
                user=request.user,
                voucher_type=data["voucher_type"],
                legal_entity=data["legal_entity"],
                date=data["date"],
                treasury_kind=data["treasury_kind"],
                treasury_id=data["treasury_id"],
                line_specs=resolved_lines,
                settlement_kind=data.get("settlement_kind"),
                party=data.get("party"),
                party_role=data.get("party_role", ""),
                payee_name=data.get("payee_name", ""),
                payment_method=data.get("payment_method", Voucher.PaymentMethod.CASH),
                reference=data.get("reference", ""),
                description=data.get("description", ""),
                exchange_rate_override=data.get("exchange_rate"),
            )
        except ExchangeRateNotFound as exc:
            return Response({"detail": str(exc.message)}, status=400)
        except TreasuryConflictError as exc:
            return Response({"detail": str(exc.message)}, status=409)
        except (VoucherValidationError, ValidationError, ValueError) as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else {"detail": str(exc)}
            return Response(detail, status=400)
        return Response(VoucherSerializer(voucher).data, status=201)

    @action(detail=False, methods=["post"])
    def transfer(self, request):
        serializer = InternalTransferCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            voucher = create_internal_transfer_voucher(
                tenant=request.user.tenant, user=request.user, legal_entity=data["legal_entity"],
                date=data["date"], treasury_kind=data["treasury_kind"], treasury_id=data["treasury_id"],
                counter_treasury_kind=data["counter_treasury_kind"], counter_treasury_id=data["counter_treasury_id"],
                amount_fc=data["amount_fc"], counter_amount_fc=data.get("counter_amount_fc"),
                reference=data.get("reference", ""), description=data.get("description", ""),
            )
        except ExchangeRateNotFound as exc:
            return Response({"detail": str(exc.message)}, status=400)
        except (VoucherValidationError, ValidationError, ValueError) as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else {"detail": str(exc)}
            return Response(detail, status=400)
        return Response(VoucherSerializer(voucher).data, status=201)

    @action(detail=True, methods=["post"])
    def post(self, request, pk=None):
        voucher = self.get_object()
        try:
            voucher, warnings = post_voucher(voucher, request.user, request=request)
        except TreasuryConflictError as exc:
            return Response({"detail": str(exc.message)}, status=409)
        except (VoucherValidationError, ValidationError, ValueError) as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else {"detail": str(exc)}
            return Response(detail, status=400)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=403)
        payload = VoucherSerializer(voucher).data
        payload["warnings"] = warnings
        status_code = 202 if voucher.status == Voucher.Status.PENDING_APPROVAL else 200
        return Response(payload, status=status_code)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        voucher = self.get_object()
        try:
            approve_voucher(voucher, request.user, request=request)
        except (VoucherValidationError, ValidationError, ValueError) as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else {"detail": str(exc)}
            return Response(detail, status=400)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=403)
        return Response(VoucherSerializer(voucher).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        voucher = self.get_object()
        serializer = RejectVoucherSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            reject_voucher(voucher, request.user, serializer.validated_data["reason"], request=request)
        except (VoucherValidationError, ValidationError, ValueError) as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else {"detail": str(exc)}
            return Response(detail, status=400)
        return Response(VoucherSerializer(voucher).data)

    @action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        voucher = self.get_object()
        try:
            withdraw_voucher(voucher, request.user, request=request)
        except (VoucherValidationError, ValidationError, ValueError) as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else {"detail": str(exc)}
            return Response(detail, status=400)
        return Response(VoucherSerializer(voucher).data)

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        voucher = self.get_object()
        serializer = RejectVoucherSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            reverse_voucher(voucher, request.user, serializer.validated_data["reason"], request=request)
        except (VoucherValidationError, ValidationError, ValueError) as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else {"detail": str(exc)}
            return Response(detail, status=400)
        return Response(VoucherSerializer(voucher).data)
