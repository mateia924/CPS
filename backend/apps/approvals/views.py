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

        return Response(list_pending_approvals(request.user))


class EmergencyApprovalsView(APIView):
    """Sprint 6.8 (decision 18, D4): `GET /api/approvals/emergency/` —
    every emergency approval on record, for review. Read from AuditLog
    directly (`after__is_emergency_approval=True`) rather than a new
    column on every approvable document model — apps.approvals.services
    .approve() already logs this fact there for every doc type
    uniformly, so this is the one place that needs to know about it."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.platform.models import AuditLog

        logs = AuditLog.objects.filter(
            tenant_id=request.user.tenant_id, action__endswith=".approved", after__is_emergency_approval=True,
        ).order_by("-created_at")
        return Response(
            [
                {
                    "id": str(log.id),
                    "doc_type": log.action.rsplit(".", 1)[0],
                    "target_id": str(log.target_id) if log.target_id else None,
                    "approved_by": str(log.actor_id) if log.actor_id else None,
                    "emergency_reason": (log.after or {}).get("emergency_reason", ""),
                    "created_at": log.created_at,
                }
                for log in logs
            ]
        )
