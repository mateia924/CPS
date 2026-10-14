from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils.translation import gettext_lazy as _
from rest_framework import filters, mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access.permissions import HasModulePermission, RequiresModuleFeature
from apps.common.viewsets import (
    EntityScopedMixin,
    EntityScopedViewSet,
    SoftDeleteDocumentViewSetMixin,
    SoftDeleteViewSetMixin,
    TenantScopedViewSet,
)
from apps.tenants.services import TenantLimitExceeded, check_warehouse_limit

from .models import (
    InventorySettings,
    ItemBarcode,
    ItemCategory,
    ItemUoM,
    StockDocument,
    StockLevel,
    UnitOfMeasure,
    Warehouse,
    set_default_warehouse,
)
from .serializers import (
    CountEntriesSerializer,
    InventorySettingsSerializer,
    ItemBarcodeSerializer,
    ItemCategorySerializer,
    ItemUoMSerializer,
    StockDocumentInputSerializer,
    StockDocumentReasonSerializer,
    StockDocumentSerializer,
    StockLevelSerializer,
    UnitOfMeasureSerializer,
    WarehouseSerializer,
)
from .services import (
    CountEntryErrors,
    StockDocumentLocked,
    _fmt_qty,
    approve_stock_document,
    confirm_transfer_receipt,
    count_drift,
    count_variances,
    create_count_session,
    create_stock_document,
    import_counts_csv,
    post_stock_document,
    reject_stock_document,
    reverse_stock_document,
    set_counts,
    submit_stock_document,
    update_stock_document,
    withdraw_stock_document,
)


class InventorySettingsView(APIView):
    """GET/PATCH the authenticated user's own tenant's inventory
    settings — one row per tenant (apps.inventory.models.
    InventorySettings), created lazily on first access, same shape as
    apps.numbering's own DocumentNumberingSetting viewset. The first
    real endpoint under /api/inventory/* — also the one the module
    gate (RequiresModuleFeature) and the 404-for-a-tenant-without-the-
    module test exercise."""

    # RequiresModuleFeature before HasModulePermission: a disabled
    # module must 404 for EVERY user, not just one who also happens to
    # lack inventory.view — permission ordering is evaluation order in
    # DRF, and the first False/raise wins.
    permission_classes = [IsAuthenticated, RequiresModuleFeature, HasModulePermission]
    permission_map = {"view": "inventory.view", "manage": "inventory.manage"}
    module_feature = "inventory"

    def get(self, request):
        settings_obj, _created = InventorySettings.objects.get_or_create(tenant=request.user.tenant)
        return Response(InventorySettingsSerializer(settings_obj).data)

    def patch(self, request):
        settings_obj, _created = InventorySettings.objects.get_or_create(tenant=request.user.tenant)
        serializer = InventorySettingsSerializer(settings_obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class ItemCategoryViewSet(SoftDeleteViewSetMixin, TenantScopedViewSet):
    """Sprint 7.1 (D7/D18). Part of the "products" module (available
    since sprint 1 — docs/catalog/modules.json), NOT gated behind
    RequiresModuleFeature("inventory") the way InventorySettingsView
    above is: a tenant with no warehouse/stock module at all can still
    want item categories (reusing the same `products.*` permission
    keys ProductViewSet already uses, not new ones)."""

    serializer_class = ItemCategorySerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = ItemCategory.objects.all()
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["code", "name"]
    ordering_fields = ["code", "name", "created_at"]
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


class UnitOfMeasureViewSet(SoftDeleteViewSetMixin, TenantScopedViewSet):
    """Sprint 7.1 (D8)."""

    serializer_class = UnitOfMeasureSerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = UnitOfMeasure.objects.all()
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["code", "name_ar"]
    ordering_fields = ["code", "created_at"]
    permission_map = {
        "list": "products.view",
        "retrieve": "products.view",
        "create": "products.manage",
        "update": "products.manage",
        "partial_update": "products.manage",
        "destroy": "products.manage",
    }


class ItemUoMViewSet(SoftDeleteViewSetMixin, TenantScopedViewSet):
    """Sprint 7.1 (D8)."""

    serializer_class = ItemUoMSerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = ItemUoM.objects.all()
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["created_at"]
    permission_map = {
        "list": "products.view",
        "retrieve": "products.view",
        "create": "products.manage",
        "update": "products.manage",
        "partial_update": "products.manage",
        "destroy": "products.manage",
    }

    def get_queryset(self):
        qs = super().get_queryset()
        item_id = self.request.query_params.get("item")
        if item_id:
            qs = qs.filter(item_id=item_id)
        return qs


class ItemBarcodeViewSet(SoftDeleteViewSetMixin, TenantScopedViewSet):
    """Sprint 7.1 (D9)."""

    serializer_class = ItemBarcodeSerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = ItemBarcode.objects.all()
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["barcode"]
    ordering_fields = ["created_at"]
    permission_map = {
        "list": "products.view",
        "retrieve": "products.view",
        "create": "products.manage",
        "update": "products.manage",
        "partial_update": "products.manage",
        "destroy": "products.manage",
    }

    def get_queryset(self):
        qs = super().get_queryset()
        item_id = self.request.query_params.get("item")
        if item_id:
            qs = qs.filter(item_id=item_id)
        return qs


class WarehouseViewSet(SoftDeleteViewSetMixin, EntityScopedViewSet):
    """Sprint 7.2 (block spec, item 1). Gated by the "inventory" module
    (unlike ItemCategory/UnitOfMeasure/ItemBarcode above, which are
    "products" — a warehouse only makes sense once a tenant has
    actually turned inventory on)."""

    serializer_class = WarehouseSerializer
    permission_classes = [IsAuthenticated, RequiresModuleFeature, HasModulePermission]
    module_feature = "inventory"
    queryset = Warehouse.objects.all()
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["code", "name"]
    ordering_fields = ["code", "created_at"]
    permission_map = {
        "list": "inventory.view",
        "retrieve": "inventory.view",
        "create": "inventory.manage",
        "update": "inventory.manage",
        "partial_update": "inventory.manage",
        "destroy": "inventory.manage",
        "deactivate": "inventory.manage",
        "activate": "inventory.manage",
        "set_default": "inventory.manage",
    }

    def get_queryset(self):
        qs = super().get_queryset()
        # 6.6.1/4: the warehouse screen's own entity column + an
        # explicit "all" filter — same optional, never-silent-default
        # query param shape as BankViewSet's own legal_entity filter.
        legal_entity_id = self.request.query_params.get("legal_entity")
        if legal_entity_id:
            qs = qs.filter(legal_entity_id=legal_entity_id)
        return qs

    def create(self, request, *args, **kwargs):
        try:
            check_warehouse_limit(request.user.tenant)
        except TenantLimitExceeded as exc:
            return Response({"detail": exc.message}, status=402)
        return super().create(request, *args, **kwargs)

    @action(detail=True, methods=["post"], url_path="set-default")
    def set_default(self, request, pk=None):
        """The one, deliberate "تبديل ذرّي" (atomic switch) action —
        unsets whatever was this warehouse's entity's old default and
        sets this one, in a single transaction (apps.inventory.models.
        set_default_warehouse). The normal create/update path refuses
        (400) to set is_default=True while a different warehouse is
        already default for that entity — this action is the only way
        to actually change it."""
        warehouse = self.get_object()
        set_default_warehouse(warehouse)
        return Response(self.get_serializer(warehouse).data)


def _decimals_as_text(value):
    """Count reports are plain dicts, not serializer output — DRF's JSON
    encoder would send their Decimals as floats. Money and quantities go
    out as exact text, like every serializer field in the project."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _decimals_as_text(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decimals_as_text(v) for v in value]
    return value


def _error_detail(exc):
    """A ValidationError's message(s) as {"detail": "..."} — the engine's
    Arabic text verbatim, never a generic fallback."""
    if hasattr(exc, "messages"):
        return {"detail": " ".join(str(m) for m in exc.messages)}
    return {"detail": str(exc)}


class StockDocumentViewSet(
    EntityScopedMixin, SoftDeleteDocumentViewSetMixin, mixins.CreateModelMixin, mixins.ListModelMixin,
    mixins.RetrieveModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet,
):
    """Sprint 7.4: إذن إضافة/صرف/تحويل (SR/SI/ST) — same shape as
    apps.vouchers.views.VoucherViewSet: `create` builds a DRAFT, every
    transition is its own action, no financial logic here at all — post/
    reverse/confirm-receipt call the 7.3 engine functions as they are.

    Entity scope (404, never 403, for anything outside it): the source
    entity, or — for a transfer only — the destination warehouse's entity,
    so a receiving branch can see what's coming. Seeing a document is not
    the right to act on it: every SENDING-side action (edit, delete,
    submit, approve, reject, withdraw, post, reverse) re-checks the SOURCE
    entity through _source_object (403). confirm-receipt is the one
    receiving-side action: it does NOT go through _source_object and
    checks only the DESTINATION entity (403 from anywhere else in scope).

    Posted-immutability is enforced HERE (update/destroy refuse anything
    past DRAFT with 409), not only by hiding buttons; 0006's trigger is
    the database backstop under it."""

    queryset = StockDocument.objects.select_related(
        "legal_entity", "warehouse", "to_warehouse__legal_entity", "party", "account",
    ).prefetch_related("lines__item", "lines__uom", "lines__cost_center", "lines__batch", "lines__serials")
    serializer_class = StockDocumentSerializer
    permission_classes = [IsAuthenticated, RequiresModuleFeature, HasModulePermission]
    module_feature = "inventory"
    permission_map = {
        "list": "inventory.view",
        "retrieve": "inventory.view",
        "incoming": "inventory.view",
        "transfer_destinations": "inventory.view",
        "create": "inventory.manage",
        "update": "inventory.manage",
        "partial_update": "inventory.manage",
        "destroy": "inventory.manage",
        "submit": "inventory.manage",
        "withdraw": "inventory.manage",
        "approve": "inventory.post",
        "reject": "inventory.post",
        "post": "inventory.post",
        "reverse": "inventory.post",
        "confirm_receipt": "inventory.post",
        "counts": "inventory.manage",
        "import_counts": "inventory.manage",
        "variances": "inventory.view",
    }

    def scope_to_accessible_entities(self, queryset):
        from django.db.models import Q

        from apps.organization.services import get_accessible_entity_ids

        accessible = get_accessible_entity_ids(self.request.user)
        return queryset.filter(
            Q(legal_entity_id__in=accessible)
            | Q(kind=StockDocument.Kind.TRANSFER, to_warehouse__legal_entity_id__in=accessible)
        )

    def get_queryset(self):
        queryset = super().get_queryset().filter(tenant=self.request.user.tenant)
        params = self.request.query_params
        for param, lookup in (
            ("kind", "kind"), ("status", "status"), ("legal_entity", "legal_entity_id"),
            ("date_from", "date__gte"), ("date_to", "date__lte"),
        ):
            if params.get(param):
                queryset = queryset.filter(**{lookup: params[param]})
        if params.get("warehouse"):
            from django.db.models import Q

            queryset = queryset.filter(Q(warehouse_id=params["warehouse"]) | Q(to_warehouse_id=params["warehouse"]))
        return queryset.order_by("-date", "-created_at")

    # -- entity checks -------------------------------------------------

    def _accessible(self):
        from apps.organization.services import get_accessible_entity_ids

        return get_accessible_entity_ids(self.request.user)

    def _source_object(self):
        document = self.get_object()
        if document.legal_entity_id not in self._accessible():
            raise PermissionDenied(_("This action belongs to the sending branch."))
        return document

    def _done(self, document, status_code=200):
        document = self.get_queryset().get(pk=document.pk)
        return Response(StockDocumentSerializer(document).data, status=status_code)

    # -- create / edit / delete ----------------------------------------

    def create(self, request, *args, **kwargs):
        serializer = StockDocumentInputSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        raw_lines = data.pop("lines", [])
        category, search = data.pop("category", None), data.pop("search", "")
        try:
            if data["kind"] == StockDocument.Kind.COUNT:
                document = create_count_session(
                    request.user.tenant, request.user, data, category=category, search=search, request=request,
                )
            else:
                document = create_stock_document(
                    request.user.tenant, request.user, data, raw_lines, request=request
                )
        except (ValidationError, ValueError) as exc:
            return Response(_error_detail(exc), status=400)
        return self._done(document, status_code=201)

    def update(self, request, *args, **kwargs):
        # The draft-only refusal lives in ONE place, update_stock_document
        # (StockDocumentLocked -> 409 below), under the row lock — not a
        # second, unlocked pre-check here.
        document = self._source_object()
        serializer = StockDocumentInputSerializer(
            data={**request.data, "kind": document.kind}, partial=kwargs.get("partial", False),
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        raw_lines = data.pop("lines", None)
        for name in ("kind", "category", "search"):
            data.pop(name, None)
        try:
            update_stock_document(document, request.user, data, raw_lines, request=request)
        except StockDocumentLocked as exc:
            return Response({"detail": str(exc)}, status=409)
        except (ValidationError, ValueError) as exc:
            return Response(_error_detail(exc), status=400)
        return self._done(document)

    def partial_update(self, request, *args, **kwargs):
        return self.update(request, *args, partial=True, **kwargs)

    def destroy(self, request, *args, **kwargs):
        self._source_object()
        return super().destroy(request, *args, **kwargs)

    def _after_soft_delete(self, instance):
        """A deleted draft takes its attachments with it: voided (the
        project's only "delete" for an attachment), never left reachable
        on a document that no longer exists."""
        from django.contrib.contenttypes.models import ContentType
        from django.utils import timezone

        from apps.attachments.models import Attachment

        Attachment.objects.filter(
            tenant=instance.tenant, content_type=ContentType.objects.get_for_model(StockDocument),
            object_id=instance.id, status=Attachment.Status.ACTIVE,
        ).update(
            status=Attachment.Status.VOIDED, void_reason="حُذف المستند المسودة",
            voided_by=self.request.user, voided_at=timezone.now(),
        )

    # -- workflow --------------------------------------------------------

    def _run(self, fn, *args, **kwargs):
        try:
            fn(*args, **kwargs)
        except (ValidationError, ValueError) as exc:
            return Response(_error_detail(exc), status=400)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=403)
        return None

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        document = self._source_object()
        error = self._run(submit_stock_document, document, request.user, request=request)
        if error:
            return error
        return self._done(document, status_code=200 if document.status == StockDocument.Status.APPROVED else 202)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        document = self._source_object()
        error = self._run(
            approve_stock_document, document, request.user, request=request,
            emergency_reason=request.data.get("emergency_reason", ""),
        )
        return error or self._done(document)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        document = self._source_object()
        error = self._run(reject_stock_document, document, request.user, request.data.get("reason", ""), request=request)
        return error or self._done(document)

    @action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        document = self._source_object()
        error = self._run(withdraw_stock_document, document, request.user, request=request)
        return error or self._done(document)

    @action(detail=True, methods=["post"])
    def post(self, request, pk=None):
        document = self._source_object()
        if document.kind == StockDocument.Kind.COUNT and request.data.get("acknowledge_drift") is not True:
            # D16 / 7.5 point (a): the variance posts against the balance
            # NOW. If that moved since the session opened, say so — by item
            # — and post only once the user has seen it.
            drift = count_drift(document)
            if drift:
                parts = [
                    f"«{d['item_name']}{' / ' + d['batch_number'] if d['batch_number'] else ''}»: "
                    f"عند فتح الجلسة {_fmt_qty(d['expected_qty'])} والرصيد الآن {_fmt_qty(d['current_qty'])} "
                    f"(الفرق {'+' if d['drift'] > 0 else ''}{_fmt_qty(d['drift'])})"
                    for d in drift
                ]
                return Response(
                    {
                        "detail": "تغيّر رصيد أصناف معدودة منذ فتح جلسة الجرد — سيُحسب الفرق على الرصيد الحالي "
                        "لا على اللقطة: " + "؛ ".join(parts) + ". أعد الترحيل بعد المراجعة لتأكيده.",
                        "drift": _decimals_as_text(drift),
                        "code": "count_drift",
                    },
                    status=409,
                )
        error = self._run(post_stock_document, document, request.user, request=request)
        return error or self._done(document)

    # -- count sessions (7.5, D16) ---------------------------------------

    def _count_errors(self, exc):
        return Response(
            {"detail": "لم يُطبَّق شيء — صحّح الأخطاء ثم أعد المحاولة.", "errors": exc.errors}, status=400
        )

    @action(detail=True, methods=["post"])
    def counts(self, request, pk=None):
        """Counted quantities by hand: {"entries": [{line, counted_qty, serials}]}
        — all applied or none (400 with every bad row)."""
        document = self._source_object()
        serializer = CountEntriesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entries = [
            {**entry, "row": index, "line": str(entry["line"])}
            for index, entry in enumerate(serializer.validated_data["entries"], start=1)
        ]
        try:
            set_counts(document, request.user, entries, request=request)
        except CountEntryErrors as exc:
            return self._count_errors(exc)
        except StockDocumentLocked as exc:
            return Response({"detail": str(exc)}, status=409)
        except ValidationError as exc:
            return Response(_error_detail(exc), status=400)
        return self._done(document)

    @action(detail=True, methods=["post"], url_path="import-counts")
    def import_counts(self, request, pk=None):
        """CSV import (multipart `file`, or `csv` as text) — atomic: one
        invalid row and nothing is applied; the 400 lists every row number
        and reason."""
        document = self._source_object()
        upload = request.FILES.get("file")
        if upload is not None:
            if upload.size > 2 * 1024 * 1024:
                return Response({"detail": "ملف العدّ أكبر من 2 ميجابايت."}, status=400)
            try:
                text = upload.read().decode("utf-8-sig")
            except UnicodeDecodeError:
                return Response({"detail": "الملف ليس نصًا بترميز UTF-8 — احفظه CSV UTF-8."}, status=400)
        else:
            text = request.data.get("csv") or ""
        try:
            import_counts_csv(document, request.user, text, request=request)
        except CountEntryErrors as exc:
            return self._count_errors(exc)
        except StockDocumentLocked as exc:
            return Response({"detail": str(exc)}, status=409)
        except ValidationError as exc:
            return Response(_error_detail(exc), status=400)
        return self._done(document)

    @action(detail=True, methods=["get"])
    def variances(self, request, pk=None):
        """«الفروق»: per line snapshot / balance now / counted / variance /
        value at the average, and the drift since the session opened."""
        document = self.get_object()
        if document.kind != StockDocument.Kind.COUNT:
            return Response({"detail": "تبويب الفروق لجلسات الجرد فقط."}, status=400)
        return Response(_decimals_as_text(count_variances(document)))

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        document = self._source_object()
        serializer = StockDocumentReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            reversal = reverse_stock_document(
                document, request.user, serializer.validated_data["reason"], request=request,
                date=serializer.validated_data.get("date"),
            )
        except (ValidationError, ValueError) as exc:
            return Response(_error_detail(exc), status=400)
        return self._done(reversal, status_code=201)

    @action(detail=True, methods=["post"], url_path="confirm-receipt")
    def confirm_receipt(self, request, pk=None):
        document = self.get_object()
        if document.kind != StockDocument.Kind.TRANSFER or document.to_warehouse_id is None:
            return Response({"detail": _("Only a transfer has a receipt to confirm.")}, status=400)
        if document.to_warehouse.legal_entity_id not in self._accessible():
            return Response(
                {"detail": _("Only the receiving branch can confirm this transfer's receipt.")}, status=403
            )
        serializer = StockDocumentReasonSerializer(data=request.data, context={"reason_optional": True})
        serializer.is_valid(raise_exception=True)
        error = self._run(
            confirm_transfer_receipt, document, request.user, date=serializer.validated_data.get("date"),
            request=request,
        )
        return error or self._done(document)

    @action(detail=False, methods=["get"], url_path="transfer-destinations")
    def transfer_destinations(self, request):
        """Warehouses a transfer from `?warehouse=` may go to: the same
        company's other active warehouses — including a branch this user
        can't otherwise see, since sending there is the source branch's
        act (the destination confirms on its own side). Only id/code/name/
        entity name — nothing else about the other branch is exposed."""
        from apps.organization.models import LegalEntity
        from apps.organization.services import company_entity_for

        source = Warehouse.objects.filter(
            tenant=request.user.tenant, id=request.query_params.get("warehouse"),
            legal_entity_id__in=self._accessible(), deleted_at__isnull=True,
        ).select_related("legal_entity").first()
        if source is None:
            return Response([])
        company = company_entity_for(source.legal_entity)
        entity_ids = [company.id, *LegalEntity.objects.filter(parent=company).values_list("id", flat=True)]
        rows = (
            Warehouse.objects.filter(
                tenant=request.user.tenant, legal_entity_id__in=entity_ids, is_active=True, deleted_at__isnull=True,
            )
            .exclude(id=source.id)
            .select_related("legal_entity")
            .order_by("code")
        )
        return Response(
            [
                {"id": str(w.id), "code": w.code, "name": w.name, "legal_entity_name": w.legal_entity.name}
                for w in rows
            ]
        )

    @action(detail=False, methods=["get"])
    def incoming(self, request):
        """«تحويلات واردة بانتظار التأكيد» — posted, unreceived, not a
        reversal, addressed to a warehouse whose entity this user holds."""
        from django.db.models import Exists, F, OuterRef

        from .models import StockMove

        received = StockMove.objects.filter(
            document=OuterRef("pk"), warehouse_id=OuterRef("to_warehouse_id"), qty_base__gt=0,
        )
        queryset = (
            self.get_queryset()
            .filter(
                kind=StockDocument.Kind.TRANSFER, status=StockDocument.Status.POSTED, reverses__isnull=True,
                to_warehouse__legal_entity_id__in=self._accessible(),
            )
            .exclude(Exists(received))
            .exclude(to_warehouse_id=F("warehouse_id"))
        )
        return Response(StockDocumentSerializer(queryset, many=True).data)


class StockLevelViewSet(EntityScopedMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """Sprint 7.4: «أرصدة المخزون» — read-only balances per item per
    warehouse, entity-scoped through the warehouse. The value is computed
    in SQL (no Python loop): the item's ItemCost for the warehouse's
    company — a branch's parent, since a branch can never sit under a
    branch (LegalEntity.clean)."""

    queryset = StockLevel.objects.select_related("item", "warehouse__legal_entity")
    serializer_class = StockLevelSerializer
    permission_classes = [IsAuthenticated, RequiresModuleFeature, HasModulePermission]
    module_feature = "inventory"
    permission_map = {"list": "inventory.view"}
    entity_lookup = "warehouse__legal_entity_id"
    filter_backends = [filters.SearchFilter]
    search_fields = ["item__sku", "item__name"]

    def get_queryset(self):
        from django.db.models import (
            Case,
            DecimalField,
            ExpressionWrapper,
            F,
            OuterRef,
            Subquery,
            Value,
            When,
        )
        from django.db.models.functions import Coalesce

        from .models import ItemCost

        company_id = Case(
            When(warehouse__legal_entity__entity_type="branch", then=F("warehouse__legal_entity__parent_id")),
            default=F("warehouse__legal_entity_id"),
        )
        avg = Subquery(
            ItemCost.objects.filter(item_id=OuterRef("item_id"), company_entity_id=OuterRef("company_id")).values(
                "avg_cost"
            )[:1]
        )
        queryset = (
            super().get_queryset()
            .filter(tenant=self.request.user.tenant)
            .annotate(company_id=company_id)
            .annotate(avg_cost=Coalesce(avg, Value(Decimal("0")), output_field=DecimalField()))
            .annotate(value=ExpressionWrapper(F("qty_on_hand") * F("avg_cost"), output_field=DecimalField()))
        )
        params = self.request.query_params
        if params.get("warehouse"):
            queryset = queryset.filter(warehouse_id=params["warehouse"])
        if params.get("legal_entity"):
            queryset = queryset.filter(warehouse__legal_entity_id=params["legal_entity"])
        if params.get("item"):
            queryset = queryset.filter(item_id=params["item"])
        if params.get("nonzero") == "true":
            queryset = queryset.exclude(qty_on_hand=0)
        return queryset.order_by("item__sku", "warehouse__code")
