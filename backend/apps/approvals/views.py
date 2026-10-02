from django.utils.translation import gettext_lazy as _
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access.permissions import HasModulePermission
from apps.common.viewsets import SoftDeleteViewSetMixin, TenantScopedViewSet

from .models import ApprovalRule
from .serializers import ApprovalRuleSerializer

# Sprint 5.5 (block 5.5.0, CFO_REVIEW_1 C10): the fixed IBAN_CHANGE rule
# seeded by approvals/migrations/0005 — 3.15.9 requires approval on
# every IBAN change with no amount threshold to configure away, so this
# one row is read-only from the "قواعد الاعتماد" screen (unlike every
# other doc_type's rules, which the tenant is free to edit/delete).
# Sprint 6.3 (decision 8): OPENING_BALANCE, seeded by approvals/
# migrations/0007, joins it — same "not editable/deletable" treatment.
_LOCKED_DOC_TYPES = {ApprovalRule.DocType.IBAN_CHANGE, ApprovalRule.DocType.OPENING_BALANCE}


class ApprovalRuleViewSet(SoftDeleteViewSetMixin, TenantScopedViewSet):
    """الإعدادات ← "قواعد الاعتماد" (3.15.1)."""

    serializer_class = ApprovalRuleSerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    queryset = ApprovalRule.objects.all()
    permission_map = {
        "list": "approvals.view",
        "retrieve": "approvals.view",
        "create": "approvals.manage",
        "update": "approvals.manage",
        "partial_update": "approvals.manage",
        "destroy": "approvals.manage",
        "deactivate": "approvals.manage",
        "activate": "approvals.manage",
    }

    def _reject_if_locked(self, instance):
        if instance.doc_type in _LOCKED_DOC_TYPES:
            return Response(
                {"detail": str(_("هذه قاعدة اعتماد ثابتة بحكم السياسة ولا يمكن تعديلها أو حذفها."))}, status=409
            )
        return None

    def update(self, request, *args, **kwargs):
        blocked = self._reject_if_locked(self.get_object())
        return blocked or super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        blocked = self._reject_if_locked(self.get_object())
        return blocked or super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        blocked = self._reject_if_locked(self.get_object())
        return blocked or super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        blocked = self._reject_if_locked(self.get_object())
        return blocked or super().deactivate(request, pk=pk)


class PendingApprovalsView(APIView):
    """صندوق الاعتماد (3.15.1/3.18): المستندات بانتظار اعتماد المستخدم
    الحالي، عبر كل أنواع المستندات — لا قائمة يدوية لكل نوع، تُستدعى
    JournalEntry/Invoice هنا مباشرة (أنواع أخرى تُضاف بنفس النمط في
    سبرنتات لاحقة)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .services import list_pending_approvals

        results, blocked = list_pending_approvals(request.user, return_blocked=True)
        return Response({"results": results, "blocked": blocked})


def _describe_emergency_document(doc_type, target_id):
    """Sprint 6.9.1 (item C): AuditLog itself only ever stored the bare
    target_id — enough to build the endpoint in 6.8, not enough to
    render a usable review screen. Resolves the same doc_type strings
    apps.approvals.services.list_pending_approvals already knows, by id
    rather than by PENDING_APPROVAL status (the document is long since
    approved by the time it shows up here)."""
    from decimal import Decimal

    from django.db.models import Sum

    from apps.accounting.models import JournalEntry, OpeningBalanceEntry, RecurringEntry
    from apps.assets.models import AssetDisposal
    from apps.sales.models import Invoice
    from apps.treasury.models import IbanChangeRequest
    from apps.vouchers.models import Voucher

    try:
        if doc_type == "journal_entry":
            entry = JournalEntry.objects.get(id=target_id)
            amount = entry.lines.aggregate(total=Sum("debit"))["total"] or Decimal("0")
            return {"number": entry.number, "description": entry.memo, "amount_base": str(amount)}
        if doc_type == "invoice":
            invoice = Invoice.objects.select_related("party").get(id=target_id)
            return {"number": invoice.number, "description": invoice.party.name, "amount_base": str(invoice.base_total)}
        if doc_type.startswith("voucher_"):
            voucher = Voucher.objects.select_related("party").get(id=target_id)
            description = voucher.party.name if voucher.party_id else voucher.payee_name
            return {"number": voucher.number, "description": description, "amount_base": str(voucher.total_base)}
        if doc_type == "iban_change":
            iban_request = IbanChangeRequest.objects.get(id=target_id)
            return {
                "number": None,
                "description": f"{iban_request.old_iban or '—'} -> {iban_request.new_iban}",
                "amount_base": "0",
            }
        if doc_type == "opening_balance":
            entry = OpeningBalanceEntry.objects.select_related("legal_entity").get(id=target_id)
            amount = entry.lines.aggregate(total=Sum("debit_base"))["total"] or Decimal("0")
            return {"number": None, "description": entry.legal_entity.name, "amount_base": str(amount)}
        if doc_type in ("recurring_entry", "asset_depreciation", "asset_addition"):
            schedule = RecurringEntry.objects.get(id=target_id)
            return {
                "number": schedule.number, "description": schedule.description,
                "amount_base": str(schedule.total_amount_base),
            }
        if doc_type == "asset_disposal":
            disposal = AssetDisposal.objects.select_related("asset").get(id=target_id)
            return {
                "number": None, "description": f"{disposal.asset.code} — {disposal.asset.name}",
                "amount_base": str(disposal.cost_share),
            }
    except (
        JournalEntry.DoesNotExist, Invoice.DoesNotExist, Voucher.DoesNotExist,
        IbanChangeRequest.DoesNotExist, OpeningBalanceEntry.DoesNotExist, RecurringEntry.DoesNotExist,
        AssetDisposal.DoesNotExist,
    ):
        pass
    return {"number": None, "description": None, "amount_base": None}


class EmergencyApprovalsView(APIView):
    """Sprint 6.8 (decision 18, D4): `GET /api/approvals/emergency/` —
    every emergency approval on record, for review. Read from AuditLog
    directly (`after__is_emergency_approval=True`) rather than a new
    column on every approvable document model — apps.approvals.services
    .approve() already logs this fact there for every doc type
    uniformly, so this is the one place that needs to know about it.
    Sprint 6.9.1 (item C): also resolves the document's own number/
    description/amount and the approver's display name — the raw ids
    AuditLog stores aren't enough to render a screen a human reads."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.accounts.models import User
        from apps.platform.models import AuditLog

        logs = AuditLog.objects.filter(
            tenant_id=request.user.tenant_id, action__endswith=".approved", after__is_emergency_approval=True,
        ).order_by("-created_at")
        users_by_id = {
            str(user.id): (user.get_full_name() or user.email)
            for user in User.objects.filter(tenant_id=request.user.tenant_id)
        }
        results = []
        for log in logs:
            doc_type = log.action.rsplit(".", 1)[0]
            target_id = str(log.target_id) if log.target_id else None
            document = _describe_emergency_document(doc_type, target_id) if target_id else {
                "number": None, "description": None, "amount_base": None,
            }
            approved_by_id = str(log.actor_id) if log.actor_id else None
            results.append(
                {
                    "id": str(log.id),
                    "doc_type": doc_type,
                    "target_id": target_id,
                    **document,
                    "approved_by": approved_by_id,
                    "approved_by_name": users_by_id.get(approved_by_id, approved_by_id),
                    "emergency_reason": (log.after or {}).get("emergency_reason", ""),
                    "created_at": log.created_at,
                }
            )
        return Response(results)
