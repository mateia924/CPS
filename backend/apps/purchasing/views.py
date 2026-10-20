from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from rest_framework import filters, mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access.permissions import HasModulePermission, RequiresModuleFeature
from apps.common.viewsets import (
    EntityScopedMixin,
    SoftDeleteDocumentViewSetMixin,
    TenantScopedViewSet,
)

from . import bills
from .models import PurchaseSettings, SupplierBill, SupplierBillLine, WithholdingTaxCode
from .serializers import (
    PurchaseSettingsSerializer,
    SupplierBillInputSerializer,
    SupplierBillSerializer,
    WithholdingTaxCodeSerializer,
)


class PurchaseSettingsView(APIView):
    """GET/PATCH the authenticated user's own tenant's purchase settings
    (R-8.5 tolerances, GRNI policy) — one row per tenant, created lazily,
    same shape as apps.inventory.views.InventorySettingsView. Gated on
    TenantFeatures.purchasing: a tenant without the module gets a 404."""

    permission_classes = [IsAuthenticated, RequiresModuleFeature, HasModulePermission]
    permission_map = {"view": "purchasing.view", "manage": "purchasing.manage"}
    module_feature = "purchasing"

    def get(self, request):
        settings_obj, _created = PurchaseSettings.objects.get_or_create(tenant=request.user.tenant)
        return Response(PurchaseSettingsSerializer(settings_obj).data)

    def patch(self, request):
        settings_obj, _created = PurchaseSettings.objects.get_or_create(tenant=request.user.tenant)
        serializer = PurchaseSettingsSerializer(settings_obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class WithholdingTaxCodeViewSet(TenantScopedViewSet):
    """Sprint 8.0 (D6): the tenant's withholding codes, read-only. They
    come only from apps/compliance/<country>/withholding.json
    (load_withholding_codes); approving or editing them is 8.3's settings
    screen, not this block's."""

    queryset = WithholdingTaxCode.objects.all()
    serializer_class = WithholdingTaxCodeSerializer
    permission_classes = [IsAuthenticated, RequiresModuleFeature, HasModulePermission]
    module_feature = "purchasing"
    permission_map = {"list": "purchasing.view", "retrieve": "purchasing.view"}
    http_method_names = ["get", "head", "options"]
    filter_backends = [filters.SearchFilter]
    search_fields = ["code", "name_ar"]


def _error_body(exc):
    """A ValidationError keeps its field names ({"bill_number": [...]})
    when it has them; otherwise {"detail": "..."} with the engine's text
    verbatim."""
    if hasattr(exc, "message_dict"):
        return exc.message_dict
    if hasattr(exc, "messages"):
        return {"detail": " ".join(str(m) for m in exc.messages)}
    return {"detail": str(exc)}


class SupplierBillViewSet(
    EntityScopedMixin, SoftDeleteDocumentViewSetMixin, mixins.CreateModelMixin, mixins.ListModelMixin,
    mixins.RetrieveModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet,
):
    """Sprint 8.1: فواتير الموردين. Same shape as the stock documents and
    vouchers: `create` builds a DRAFT, every transition is its own action,
    the money lives in apps.purchasing.bills. Posted-immutability is here
    (update/destroy refuse anything past DRAFT with 409), not only in the
    buttons. Entity scope: 404 outside it (EntityScopedMixin).

    List filters: status, supplier, legal_entity (absent = every entity
    the user can see, the list's «الكل»), due_before/due_after, date_from/
    date_to, search on our number and the supplier's."""

    queryset = SupplierBill.objects.select_related("legal_entity", "supplier", "journal_entry").prefetch_related(
        "lines__account", "lines__cost_center", "lines__tax_code", "lines__wht_code", "lines__asset"
    )
    serializer_class = SupplierBillSerializer
    permission_classes = [IsAuthenticated, RequiresModuleFeature, HasModulePermission]
    module_feature = "purchasing"
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["number", "bill_number", "supplier__name"]
    ordering_fields = ["date", "due_date", "number", "total", "created_at"]
    permission_map = {
        "list": "purchasing.view",
        "retrieve": "purchasing.view",
        "form_options": "purchasing.view",
        "create": "purchasing.manage",
        "update": "purchasing.manage",
        "partial_update": "purchasing.manage",
        "destroy": "purchasing.manage",
        "submit": "purchasing.manage",
        "withdraw": "purchasing.manage",
        "approve": "purchasing.post",
        "reject": "purchasing.post",
        "post": "purchasing.post",
        "reverse": "purchasing.post",
        # Sprint 8.2: paying the bill also writes a payment voucher, so
        # pay_now re-checks vouchers.post inside (403 without it).
        "pay_now": "purchasing.post",
        "open_advances": "purchasing.view",
        "apply_advance": "purchasing.post",
        "withdraw_advance": "purchasing.post",
    }

    def get_queryset(self):
        queryset = bills.with_balances(super().get_queryset().filter(tenant=self.request.user.tenant))
        params = self.request.query_params
        # Sprint 8.2: what can still be paid — the voucher screen's open
        # items for a supplier, and the aging's source.
        if params.get("open") in ("1", "true"):
            queryset = queryset.filter(status=SupplierBill.Status.POSTED, balance_fc__gt=0)
        for param, lookup in (
            ("status", "status"), ("supplier", "supplier_id"), ("legal_entity", "legal_entity_id"),
            ("due_before", "due_date__lte"), ("due_after", "due_date__gte"),
            ("date_from", "date__gte"), ("date_to", "date__lte"),
        ):
            if params.get(param):
                queryset = queryset.filter(**{lookup: params[param]})
        return queryset.order_by("-date", "-created_at")

    @action(detail=False, methods=["get"], url_path="form-options")
    def form_options(self, request):
        """Everything the bill form picks from, behind the bill's own
        permission — a Purchasing user (purchasing.view/manage only) holds
        none of accounting.view, parties.view, organization.view or
        costcenters.view, and the form must not depend on them."""
        from apps.accounting.models import Account, TaxCode
        from apps.assets.models import Asset
        from apps.organization.models import CostCenter, LegalEntity
        from apps.organization.services import get_accessible_entity_ids
        from apps.parties.models import PartyRole

        tenant = request.user.tenant
        features = tenant.features
        roles = (
            PartyRole.objects.filter(party__tenant=tenant, role=PartyRole.Role.SUPPLIER, is_active=True)
            .select_related("party").order_by("party__name")
        )
        accounts = [
            a for a in Account.objects.filter(
                tenant=tenant, is_active=True, allow_posting=True, allow_manual_posting=True,
            ).order_by("code")
            if a.can_post
        ]
        return Response(
            {
                "legal_entities": [
                    {"id": str(e.id), "code": e.code, "name": e.name, "base_currency": e.base_currency}
                    for e in LegalEntity.objects.filter(
                        tenant=tenant, id__in=get_accessible_entity_ids(request.user)
                    ).exclude(entity_type=LegalEntity.Type.HOLDING).order_by("code")
                ],
                "suppliers": [
                    {
                        "id": str(r.party_id), "code": r.party.code, "name": r.party.name,
                        "default_expense_account": str(r.default_expense_account_id) if r.default_expense_account_id else None,
                        "payment_terms_days": (r.details or {}).get("payment_terms_days"),
                    }
                    for r in roles
                ],
                "accounts": [{"id": str(a.id), "code": a.code, "name": a.name, "type": a.type} for a in accounts],
                "cost_centers": [
                    {"id": str(c.id), "code": c.code, "name": c.name}
                    for c in CostCenter.objects.filter(tenant=tenant, is_active=True, deleted_at__isnull=True).order_by("code")
                ] if features.cost_centers else [],
                "cost_center_required": bool(features.cost_center_required),
                "tax_codes": [
                    {"id": str(c.id), "code": c.code, "name": c.name, "rate": str(c.rate), "kind": c.kind,
                     "deductible": c.deductible}
                    for c in TaxCode.objects.filter(tenant=tenant, is_active=True).order_by("code")
                ],
                "wht_codes": [
                    {"id": str(c.id), "code": c.code, "name_ar": c.name_ar, "rate": str(c.rate), "base": c.base,
                     "is_example": c.is_example}
                    for c in WithholdingTaxCode.objects.filter(tenant=tenant, is_active=True)
                ],
                "asset_categories": [{"value": v, "label": str(label)} for v, label in Asset.Category.choices],
            }
        )

    def _done(self, bill, status_code=200, warnings=None):
        bill = self.get_queryset().get(pk=bill.pk)
        data = SupplierBillSerializer(bill).data
        if warnings is not None:
            data["warnings"] = warnings
        return Response(data, status=status_code)

    def _input(self, request, partial=False):
        serializer = SupplierBillInputSerializer(data=request.data, partial=partial, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        raw_lines = data.pop("lines", None)
        return data, raw_lines, [str(w) for w in getattr(serializer, "rate_warnings", [])]

    def create(self, request, *args, **kwargs):
        data, raw_lines, warnings = self._input(request)
        try:
            bill = bills.create_supplier_bill(request.user.tenant, request.user, data, raw_lines or [], request=request)
        except (ValidationError, ValueError) as exc:
            return Response(_error_body(exc), status=400)
        return self._done(bill, status_code=201, warnings=warnings)

    def update(self, request, *args, **kwargs):
        bill = self.get_object()
        data, raw_lines, warnings = self._input(request, partial=kwargs.get("partial", False))
        try:
            bills.update_supplier_bill(bill, request.user, data, raw_lines, request=request)
        except bills.SupplierBillLocked as exc:
            return Response({"detail": str(exc)}, status=409)
        except (ValidationError, ValueError) as exc:
            return Response(_error_body(exc), status=400)
        return self._done(bill, warnings=warnings)

    def partial_update(self, request, *args, **kwargs):
        return self.update(request, *args, partial=True, **kwargs)

    def _after_soft_delete(self, instance):
        """A deleted draft takes its attachments with it (voided), same as a
        deleted stock document."""
        from django.contrib.contenttypes.models import ContentType
        from django.utils import timezone

        from apps.attachments.models import Attachment

        Attachment.objects.filter(
            tenant=instance.tenant, content_type=ContentType.objects.get_for_model(SupplierBill),
            object_id=instance.id, status=Attachment.Status.ACTIVE,
        ).update(
            status=Attachment.Status.VOIDED, void_reason="حُذفت الفاتورة المسودة",
            voided_by=self.request.user, voided_at=timezone.now(),
        )

    def _run(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs), None
        except (ValidationError, ValueError) as exc:
            return None, Response(_error_body(exc), status=400)
        except PermissionDenied as exc:
            return None, Response({"detail": str(exc)}, status=403)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        bill, error = self._run(bills.submit_supplier_bill, self.get_object(), request.user, request=request)
        if error:
            return error
        bill.refresh_from_db()
        return self._done(bill, status_code=200 if bill.status == SupplierBill.Status.APPROVED else 202)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        bill = self.get_object()
        _result, error = self._run(
            bills.approve_supplier_bill, bill, request.user, request=request,
            emergency_reason=request.data.get("emergency_reason", ""),
        )
        return error or self._done(bill)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        bill = self.get_object()
        _result, error = self._run(bills.reject_supplier_bill, bill, request.user, request.data.get("reason", ""), request=request)
        return error or self._done(bill)

    @action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        bill = self.get_object()
        _result, error = self._run(bills.withdraw_supplier_bill, bill, request.user, request=request)
        return error or self._done(bill)

    @action(detail=True, methods=["post"])
    def post(self, request, pk=None):
        bill = self.get_object()
        _result, error = self._run(bills.post_supplier_bill, bill, request.user, request=request)
        return error or self._done(bill)

    # -- sprint 8.2: payment ----------------------------------------------------

    @action(detail=True, methods=["post"], url_path="pay-now")
    def pay_now(self, request, pk=None):
        """«دفع نقدي الآن»: {treasury_kind, treasury_id, payment_method?, date?}
        -> a payment voucher fully allocated to the bill, posted (or held by
        its approval rule). Returns the voucher's id/number/status."""
        from apps.access.services import user_has_permission

        from . import payments

        bill = self.get_object()
        if not user_has_permission(request.user, "vouchers.post"):
            return Response({"detail": "الدفع ينشئ سند صرف ويرحّله — يتطلب صلاحية ترحيل السندات."}, status=403)
        data = request.data
        if not data.get("treasury_kind") or not data.get("treasury_id"):
            return Response({"treasury_id": ["اختر حساب الخزينة الذي يُدفع منه."]}, status=400)
        try:
            voucher, warnings = payments.pay_now(
                bill, request.user, data["treasury_kind"], data["treasury_id"], data.get("payment_method") or "cash",
                request=request,
            )
        except (ValidationError, ValueError) as exc:
            return Response(_error_body(exc), status=400)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=403)
        return Response(
            {"voucher_id": str(voucher.id), "voucher_number": voucher.number, "voucher_status": voucher.status,
             "warnings": [str(w) for w in warnings]},
            status=201,
        )

    @action(detail=True, methods=["get"], url_path="open-advances")
    def open_advances(self, request, pk=None):
        from . import payments

        bill = self.get_object()
        return Response([
            {
                "line_id": str(line.id), "voucher_id": str(line.voucher_id), "voucher_number": line.voucher.number,
                "date": line.voucher.date, "kind": line.line_type, "amount_fc": str(line.amount_fc),
                "remaining_fc": str(remaining), "currency": line.voucher.currency,
            }
            for line, remaining in payments.open_advances(bill)
        ])

    @action(detail=True, methods=["post"], url_path="apply-advance")
    def apply_advance(self, request, pk=None):
        """{source_line, amount} — apply a supplier advance to this bill."""
        from apps.vouchers.models import VoucherLine

        from . import payments

        bill = self.get_object()
        line = VoucherLine.objects.filter(voucher__tenant=request.user.tenant, id=request.data.get("source_line")).first()
        if line is None:
            return Response({"source_line": ["الدفعة المقدمة غير موجودة."]}, status=400)
        try:
            amount = Decimal(str(request.data.get("amount")))
        except Exception:  # noqa: BLE001 — any unparsable amount is the same 400
            return Response({"amount": ["مبلغ غير صالح."]}, status=400)
        _result, error = self._run(payments.apply_advance, bill, line, amount, request.user, request=request)
        return error or self._done(bill)

    @action(detail=True, methods=["post"], url_path="withdraw-advance")
    def withdraw_advance(self, request, pk=None):
        """{application, reason} — undo an advance application."""
        from . import payments
        from .models import AdvanceApplication

        bill = self.get_object()
        application = AdvanceApplication.objects.filter(
            tenant=request.user.tenant, supplier_bill=bill, id=request.data.get("application")
        ).first()
        if application is None:
            return Response({"application": ["التخصيص غير موجود."]}, status=400)
        _result, error = self._run(payments.withdraw_application, application, request.user, request.data.get("reason", ""), request=request)
        return error or self._done(bill)

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        bill = self.get_object()
        _result, error = self._run(bills.reverse_supplier_bill, bill, request.user, request.data.get("reason", ""), request=request)
        return error or self._done(bill)


class ExpensesView(APIView):
    """Sprint 8.1: «المصروفات» — every posted expense line in one list:
    EXPENSE lines of posted supplier bills, and the direct-account lines of
    posted payment vouchers on an expense account (5.3's «بند المصروف
    المباشر», which stays where it is). Each source only for a user who may
    see it: bill lines need purchasing.view (the endpoint's own gate),
    voucher lines also vouchers.view. Entity scope as everywhere.

    Amount = what the expense account was debited, in the document's
    currency and in base: a bill line's cost (net + capitalized VAT); a
    voucher line's net, plus its VAT when that VAT is non-deductible —
    the same split apps.vouchers.services posts. Filters: date_from,
    date_to, account, cost_center, legal_entity, source."""

    permission_classes = [IsAuthenticated, RequiresModuleFeature, HasModulePermission]
    permission_map = {"view": "purchasing.view"}
    module_feature = "purchasing"
    page_size = 25

    def get(self, request):
        from apps.access.services import user_has_permission
        from apps.accounting.models import Account, TaxCode
        from apps.organization.services import get_accessible_entity_ids
        from apps.vouchers.models import Voucher, VoucherLine
        from apps.vouchers.services import _account_line_tax_split

        user = request.user
        params = request.query_params
        entities = get_accessible_entity_ids(user)
        if params.get("legal_entity"):
            entities = [e for e in entities if str(e) == params["legal_entity"]]
        rows = []

        if params.get("source") in (None, "", "supplier_bill"):
            bill_lines = SupplierBillLine.objects.filter(
                bill__tenant=user.tenant, bill__status=SupplierBill.Status.POSTED, bill__deleted_at__isnull=True,
                bill__legal_entity_id__in=entities, line_type=SupplierBillLine.LineType.EXPENSE,
            ).select_related("bill__supplier", "bill__legal_entity", "account", "cost_center")
            bill_lines = self._filtered(bill_lines, params, "bill__date")
            for line in bill_lines:
                bill = line.bill
                rows.append(
                    self._row(
                        line.id, "supplier_bill", bill.id, bill.number, bill.date, bill.supplier.name, bill.legal_entity.name,
                        line.account, line.cost_center, line.description, line.cost, bill.currency,
                        (line.cost * bill.exchange_rate).quantize(Decimal("0.01")),
                    )
                )

        if params.get("source") in (None, "", "voucher") and user_has_permission(user, "vouchers.view"):
            voucher_lines = VoucherLine.objects.filter(
                voucher__tenant=user.tenant, voucher__status=Voucher.Status.POSTED, voucher__deleted_at__isnull=True,
                voucher__voucher_type=Voucher.VoucherType.PAYMENT, voucher__legal_entity_id__in=entities,
                line_type=VoucherLine.LineType.ACCOUNT, account__type=Account.Type.EXPENSE,
            ).select_related("voucher__party", "voucher__legal_entity", "account", "cost_center", "tax_code")
            voucher_lines = self._filtered(voucher_lines, params, "voucher__date")
            for line in voucher_lines:
                voucher = line.voucher
                net, tax, _gross = _account_line_tax_split(line.amount_fc, line.tax_code, line.amount_includes_tax)
                folded = line.tax_code is not None and line.tax_code.deductible == TaxCode.Deductible.NONE
                amount = net + tax if folded else net
                rows.append(
                    self._row(
                        line.id, "voucher", voucher.id, voucher.number, voucher.date,
                        voucher.party.name if voucher.party_id else voucher.payee_name, voucher.legal_entity.name,
                        line.account, line.cost_center, line.description, amount, voucher.currency,
                        (amount * voucher.exchange_rate).quantize(Decimal("0.01")),
                    )
                )

        rows.sort(key=lambda r: (r["date"], r["number"]), reverse=True)
        total_base = sum((Decimal(r["amount_base"]) for r in rows), Decimal("0"))
        try:
            page = max(1, int(params.get("page", 1)))
        except ValueError:
            page = 1
        start = (page - 1) * self.page_size
        return Response(
            {"count": len(rows), "total_base": str(total_base), "results": rows[start:start + self.page_size]}
        )

    @staticmethod
    def _filtered(queryset, params, date_field):
        if params.get("date_from"):
            queryset = queryset.filter(**{f"{date_field}__gte": params["date_from"]})
        if params.get("date_to"):
            queryset = queryset.filter(**{f"{date_field}__lte": params["date_to"]})
        if params.get("account"):
            queryset = queryset.filter(account_id=params["account"])
        if params.get("cost_center"):
            queryset = queryset.filter(cost_center_id=params["cost_center"])
        return queryset

    @staticmethod
    def _row(line_id, source, doc_id, number, date, party_name, entity_name, account, cost_center, description, amount,
             currency, amount_base):
        return {
            "id": f"{source}:{line_id}",
            "source": source, "document_id": str(doc_id), "number": number, "date": date.isoformat(),
            "party_name": party_name, "legal_entity_name": entity_name,
            "account": str(account.id), "account_code": account.code, "account_name": account.name,
            "cost_center": str(cost_center.id) if cost_center else None,
            "cost_center_name": cost_center.name if cost_center else None,
            "description": description, "amount": str(amount), "currency": currency, "amount_base": str(amount_base),
        }


class PayablesByWeekView(APIView):
    """Sprint 8.2: «مستحقات الدفع بالأسبوع» (apps.reports.services.
    payables_by_week). Under purchasing, not reports: it is the purchasing
    and treasury planning view, readable with purchasing.view (the
    Purchasing role holds no accounting.view). Entity: ?legal_entity=, else
    every entity the user can see."""

    permission_classes = [IsAuthenticated, RequiresModuleFeature, HasModulePermission]
    permission_map = {"view": "purchasing.view"}
    module_feature = "purchasing"

    def get(self, request):
        import datetime

        from apps.organization.models import LegalEntity
        from apps.organization.services import get_accessible_entity_ids
        from apps.reports.services import payables_by_week

        legal_entity = None
        if request.query_params.get("legal_entity"):
            legal_entity = LegalEntity.objects.filter(
                tenant=request.user.tenant, id=request.query_params["legal_entity"],
                id__in=get_accessible_entity_ids(request.user),
            ).first()
            if legal_entity is None:
                return Response({"legal_entity": ["الكيان غير موجود."]}, status=400)
        as_of = request.query_params.get("as_of")
        result = payables_by_week(
            request.user.tenant, legal_entity, datetime.date.fromisoformat(as_of) if as_of else None
        )
        accessible = {str(e) for e in get_accessible_entity_ids(request.user)}
        if legal_entity is None:
            # Owner sees all; anyone else only their entities' bills.
            from .models import SupplierBill

            allowed = set(
                str(i) for i in SupplierBill.objects.filter(
                    tenant=request.user.tenant, legal_entity_id__in=accessible
                ).values_list("id", flat=True)
            )
            for bucket in result["buckets"]:
                bucket["bills"] = [b for b in bucket["bills"] if b["id"] in allowed]
                bucket["total"] = sum((b["amount_base"] for b in bucket["bills"]), Decimal("0"))
            result["total"] = sum((b["total"] for b in result["buckets"]), Decimal("0"))
        for bucket in result["buckets"]:
            bucket["total"] = str(bucket["total"])
            for b in bucket["bills"]:
                b["balance_fc"], b["amount_base"] = str(b["balance_fc"]), str(b["amount_base"])
        result["total"] = str(result["total"])
        return Response(result)
