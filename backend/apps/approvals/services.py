from django.core.exceptions import PermissionDenied, ValidationError
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


def submit_for_approval(document, user, doc_type, amount_base, request=None):
    """DRAFT -> PENDING_APPROVAL, then immediately auto-approved if no
    rule matches this doc_type/amount — "لا قاعدة مطابقة = اعتماد
    تلقائي عند الإرسال". Returns True if it ended up auto-approved,
    False if it's genuinely waiting (a human still needs to call
    approve())."""
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


def approve(document, user, doc_type, amount_base, request=None):
    """3.15.9 segregation of duties: the creator can never approve
    their own document — except in a single-active-user tenant
    ("الوضع المبسّط"), where there is nobody else who could; that
    exemption is itself logged (3.15.1: "يُعفى تلقائيًا مع تسجيل
    ذلك")."""
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


def reject(document, user, doc_type, reason, request=None):
    if document.status != STATUS_PENDING_APPROVAL:
        raise ValidationError(_("Only a pending-approval document can be rejected."))
    if not reason:
        raise ValidationError(_("A reason is required to reject a document."))

    document.status = STATUS_DRAFT
    document.save(update_fields=["status"])
    _log(document, doc_type, user, "rejected", after={"reason": reason}, request=request)
    return document
