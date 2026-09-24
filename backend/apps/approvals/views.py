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
_LOCKED_DOC_TYPES = {ApprovalRule.DocType.IBAN_CHANGE}


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
                {"detail": "This approval rule is fixed by policy and cannot be changed."}, status=409
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
