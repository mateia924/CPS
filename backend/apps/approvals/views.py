from decimal import Decimal

from django.db.models import Sum
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access.permissions import HasModulePermission
from apps.common.viewsets import SoftDeleteViewSetMixin, TenantScopedViewSet

from .models import ApprovalRule
from .serializers import ApprovalRuleSerializer
from .services import get_matching_rule


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


class PendingApprovalsView(APIView):
    """صندوق الاعتماد (3.15.1/3.18): المستندات بانتظار اعتماد المستخدم
    الحالي، عبر كل أنواع المستندات — لا قائمة يدوية لكل نوع، تُستدعى
    JournalEntry/Invoice هنا مباشرة (أنواع أخرى تُضاف بنفس النمط في
    سبرنتات لاحقة)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.accounting.models import JournalEntry
        from apps.sales.models import Invoice

        user = request.user
        tenant = user.tenant
        user_role_ids = set(user.roles.values_list("id", flat=True))
        results = []

        for entry in JournalEntry.objects.filter(tenant=tenant, status="pending_approval"):
            amount = entry.lines.aggregate(total=Sum("debit"))["total"] or Decimal("0")
            rule = get_matching_rule(tenant, "journal_entry", amount)
            if rule is not None and rule.required_role_id in user_role_ids:
                results.append(
                    {
                        "doc_type": "journal_entry",
                        "id": str(entry.id),
                        "number": entry.number,
                        "date": entry.date,
                        "description": entry.memo,
                        "amount_base": str(amount),
                        "created_by": str(entry.created_by_id) if entry.created_by_id else None,
                    }
                )

        for invoice in Invoice.objects.filter(tenant=tenant, status="pending_approval"):
            rule = get_matching_rule(tenant, "invoice", invoice.base_total)
            if rule is not None and rule.required_role_id in user_role_ids:
                results.append(
                    {
                        "doc_type": "invoice",
                        "id": str(invoice.id),
                        "number": invoice.number,
                        "date": invoice.issue_date,
                        "description": invoice.party.name,
                        "amount_base": str(invoice.base_total),
                        "created_by": str(invoice.created_by_id) if invoice.created_by_id else None,
                    }
                )

        return Response(results)
