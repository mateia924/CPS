from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from apps.platform.models import AuditLog
from apps.platform.services import log_action

from .models import ApprovalRule

# Sprint 4.5 (3.15.1): the shared intermediate-state vocabulary every
# approvable document uses, whatever its own final/terminal states are
# (JournalEntry: posted/reversed via DocumentStateMixin; Invoice: its
# own issued/paid/cancelled, extended with these two — see the Decision
# Log for why Invoice doesn't literally inherit DocumentStateMixin).
STATUS_DRAFT = "draft"
STATUS_PENDING_APPROVAL = "pending_approval"
STATUS_APPROVED = "approved"


def get_matching_rule(tenant, doc_type, amount_base):
    """The highest-min_amount active rule the amount still qualifies
    for, or None (= auto-approve, no gate for this doc_type/amount)."""
    return (
        ApprovalRule.objects.filter(
            tenant=tenant, doc_type=doc_type, is_active=True, min_amount__lte=amount_base
        )
        .order_by("-min_amount")
        .first()
    )


def list_pending_approvals(user):
    """صندوق الاعتماد (3.15.1/3.18): every PENDING_APPROVAL document
    across doc types this `user` is eligible to act on — extracted from
    apps.approvals.views.PendingApprovalsView (sprint 6.0.1-B) so the
    dashboard summary card can reuse the exact same eligibility rule
    for its own count instead of re-deriving it."""
    from decimal import Decimal

    from django.db.models import Sum

    from apps.accounting.models import JournalEntry
    from apps.sales.models import Invoice
    from apps.treasury.models import IbanChangeRequest
    from apps.vouchers.models import Voucher

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

    # Sprint 5.4: vouchers (3.8) join the same inbox, same pattern —
    # doc_type is f"voucher_{voucher_type}" (matching submit_for_
    # approval's call in apps.vouchers.services.post_voucher).
    for voucher in Voucher.objects.filter(tenant=tenant, status="pending_approval"):
        doc_type = f"voucher_{voucher.voucher_type}"
        rule = get_matching_rule(tenant, doc_type, voucher.total_base)
        if rule is not None and rule.required_role_id in user_role_ids:
            results.append(
                {
                    "doc_type": doc_type,
                    "id": str(voucher.id),
                    "number": voucher.number,
                    "date": voucher.date,
                    "description": voucher.party.name if voucher.party_id else voucher.payee_name,
                    "amount_base": str(voucher.total_base),
                    "created_by": str(voucher.created_by_id) if voucher.created_by_id else None,
                }
            )

    # Sprint 5.5 (block 5.5.0): IBAN change requests join the same
    # inbox — always min_amount=0, so any PENDING_APPROVAL row's
    # matching rule is the fixed one (required_role=Owner).
    for iban_request in IbanChangeRequest.objects.filter(
        tenant=tenant, status="pending_approval"
    ).select_related("content_type"):
        rule = get_matching_rule(tenant, "iban_change", Decimal("0"))
        if rule is not None and rule.required_role_id in user_role_ids:
            results.append(
                {
                    "doc_type": "iban_change",
                    "id": str(iban_request.id),
                    "number": None,
                    "date": iban_request.created_at.date(),
                    "description": f"{iban_request.old_iban or '—'} -> {iban_request.new_iban}",
                    "amount_base": "0",
                    "created_by": str(iban_request.created_by_id),
                }
            )

    return results


def _is_single_active_user_tenant(tenant):
    return tenant.users.filter(is_active=True).count() <= 1


def _log(document, doc_type, user, action, before=None, after=None, request=None):
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER,
        actor_id=user.id if user else None,
        action=f"{doc_type}.{action}",
        target_type=doc_type,
        target_id=document.id,
        tenant_id=document.tenant_id,
        before=before,
        after=after,
        request=request,
    )


def _lock(document):
    """CFO_REVIEW_1 C4: acquires the row lock and syncs `document`'s
    in-memory `status` to what's actually in the DB right now — every
    caller keeps its own reference to the SAME object (nothing here
    returns a new instance), so this is safe to insert into any
    already-mutating function without touching its callers at all. Must
    be called inside an open `transaction.atomic()` block."""
    document.status = type(document).objects.select_for_update().get(pk=document.pk).status
    return document


@transaction.atomic
def submit_for_approval(document, user, doc_type, amount_base, request=None):
    """DRAFT -> PENDING_APPROVAL, then immediately auto-approved if no
    rule matches this doc_type/amount — "لا قاعدة مطابقة = اعتماد
    تلقائي عند الإرسال". Returns True if it ended up auto-approved,
    False if it's genuinely waiting (a human still needs to call
    approve())."""
    _lock(document)
    if document.status != STATUS_DRAFT:
        raise ValidationError(_("Only a draft document can be submitted for approval."))

    document.status = STATUS_PENDING_APPROVAL
    document.save(update_fields=["status"])
    _log(document, doc_type, user, "submitted")

    rule = get_matching_rule(document.tenant, doc_type, amount_base)
    if rule is None:
        document.status = STATUS_APPROVED
        document.save(update_fields=["status"])
        _log(document, doc_type, user, "auto_approved", request=request)
        return True
    return False


def can_approve(document, user, doc_type, amount_base):
    """True if `user` is allowed to approve this specific document right
    now (no matching rule at all is treated as "anyone may", since
    submit_for_approval would already have auto-approved it — this
    only matters when called speculatively, e.g. from the frontend, on
    a document still at PENDING_APPROVAL for some other reason)."""
    rule = get_matching_rule(document.tenant, doc_type, amount_base)
    if rule is None:
        return True
    if _is_single_active_user_tenant(document.tenant):
        return True
    if document.created_by_id == user.id:
        return False
    return document.tenant_id == user.tenant_id and user.roles.filter(id=rule.required_role_id).exists()


@transaction.atomic
def approve(document, user, doc_type, amount_base, request=None):
    """3.15.9 segregation of duties: the creator can never approve
    their own document — except in a single-active-user tenant
    ("الوضع المبسّط"), where there is nobody else who could; that
    exemption is itself logged (3.15.1: "يُعفى تلقائيًا مع تسجيل
    ذلك")."""
    _lock(document)
    if document.status != STATUS_PENDING_APPROVAL:
        raise ValidationError(_("Only a pending-approval document can be approved."))

    rule = get_matching_rule(document.tenant, doc_type, amount_base)
    exempted = rule is not None and _is_single_active_user_tenant(document.tenant)
    if rule is not None and not exempted:
        if document.created_by_id == user.id:
            raise PermissionDenied(_("You cannot approve a document you created yourself."))
        if not user.roles.filter(id=rule.required_role_id).exists():
            raise PermissionDenied(_("You do not have the required role to approve this document."))

    document.status = STATUS_APPROVED
    document.save(update_fields=["status"])
    _log(
        document, doc_type, user, "approved",
        after={"single_user_tenant_exemption": exempted} if exempted else None,
        request=request,
    )
    return document


@transaction.atomic
def reject(document, user, doc_type, reason, request=None):
    _lock(document)
    if document.status != STATUS_PENDING_APPROVAL:
        raise ValidationError(_("Only a pending-approval document can be rejected."))
    if not reason:
        raise ValidationError(_("A reason is required to reject a document."))

    document.status = STATUS_DRAFT
    document.save(update_fields=["status"])
    _log(document, doc_type, user, "rejected", after={"reason": reason}, request=request)
    return document


@transaction.atomic
def withdraw(document, user, doc_type, request=None):
    """CFO_REVIEW_1 C3: the creator's own way back to DRAFT — unlike
    reject() (an approver sending it back), only the document's own
    creator may withdraw it, and no reason is required. Same shared
    engine used by submit_for_approval/approve/reject above; mirrors
    apps.vouchers.services.withdraw_voucher's already-proven semantics
    (5.3), generalized here for JournalEntry/Invoice."""
    _lock(document)
    if document.status != STATUS_PENDING_APPROVAL:
        raise ValidationError(_("Only a pending-approval document can be withdrawn."))
    if document.created_by_id != user.id:
        raise PermissionDenied(_("Only the creator can withdraw this document."))

    document.status = STATUS_DRAFT
    document.save(update_fields=["status"])
    _log(document, doc_type, user, "withdrawn", request=request)
    return document
