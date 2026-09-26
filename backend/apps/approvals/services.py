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

    from apps.accounting.models import JournalEntry, OpeningBalanceEntry, RecurringEntry
    from apps.sales.models import Invoice
    from apps.treasury.models import IbanChangeRequest
    from apps.vouchers.models import Voucher

    tenant = user.tenant
    user_role_ids = set(user.roles.values_list("id", flat=True))
    # Sprint 6.9.1 (item A, decision 2): the same single-active-user
    # exemption approve() already grants (3.15.1) — without it, the one
    # user on such a tenant could approve any of these documents
    # (approve() lets them through) but never actually saw them here,
    # since none matched their own role.
    exempted = _is_single_active_user_tenant(tenant)
    results = []

    for entry in JournalEntry.objects.filter(tenant=tenant, status="pending_approval"):
        amount = entry.lines.aggregate(total=Sum("debit"))["total"] or Decimal("0")
        rule = get_matching_rule(tenant, "journal_entry", amount)
        if rule is not None and (exempted or rule.required_role_id in user_role_ids):
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
        if rule is not None and (exempted or rule.required_role_id in user_role_ids):
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
        if rule is not None and (exempted or rule.required_role_id in user_role_ids):
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
        if rule is not None and (exempted or rule.required_role_id in user_role_ids):
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

    # Sprint 6.8 (real gap found while wiring the digest, decision 17):
    # opening balances (6.3) and recurring entries (6.4) both added
    # their own PENDING_APPROVAL doc types but were never added here —
    # neither the inbox screen nor the dashboard's pending count ever
    # showed either. Fixed here, the one shared eligibility function
    # both already read from.
    for entry in OpeningBalanceEntry.objects.filter(tenant=tenant, status="pending_approval").select_related(
        "legal_entity"
    ):
        amount = entry.lines.aggregate(total=Sum("debit_base"))["total"] or Decimal("0")
        rule = get_matching_rule(tenant, "opening_balance", amount)
        if rule is not None and (exempted or rule.required_role_id in user_role_ids):
            results.append(
                {
                    "doc_type": "opening_balance",
                    "id": str(entry.id),
                    "number": None,
                    "date": entry.opening_date,
                    "description": entry.legal_entity.name,
                    "amount_base": str(amount),
                    "created_by": str(entry.created_by_id) if entry.created_by_id else None,
                }
            )

    for schedule in RecurringEntry.objects.filter(tenant=tenant, status="pending_approval"):
        # Sprint 6.5 (decision 11): a DEPRECIATION-kind schedule is
        # approved through its own doc_type/rule ("asset_depreciation"
        # or "asset_addition", never "recurring_entry") — the
        # authorities are configured independently.
        if schedule.kind == RecurringEntry.Kind.DEPRECIATION:
            from apps.assets.depreciation import doc_type_for_entry

            doc_type = doc_type_for_entry(schedule)
        else:
            doc_type = "recurring_entry"
        rule = get_matching_rule(tenant, doc_type, schedule.total_amount_base)
        if rule is not None and (exempted or rule.required_role_id in user_role_ids):
            results.append(
                {
                    "doc_type": doc_type,
                    "id": str(schedule.id),
                    "number": schedule.number,
                    "date": schedule.created_at.date(),
                    "description": schedule.description,
                    "amount_base": str(schedule.total_amount_base),
                    "created_by": str(schedule.created_by_id) if schedule.created_by_id else None,
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


def _check_mandatory_attachments(document, doc_type, amount_base):
    """Sprint 6.7 (3.17 rule 4, decision 15): every active AttachmentRule
    matching this doc_type at this amount must have a corresponding
    ACTIVE attachment already on the document — checked here, the one
    choke point every document type's submit/issue/post path already
    goes through, so no doc-type-specific copy of this check exists
    anywhere else."""
    from django.contrib.contenttypes.models import ContentType

    from apps.attachments.models import Attachment, AttachmentRule

    rules = AttachmentRule.objects.filter(
        tenant=document.tenant, doc_type=doc_type, is_active=True, min_amount_base__lte=amount_base
    )
    if not rules:
        return
    content_type = ContentType.objects.get_for_model(type(document))
    for rule in rules:
        has_attachment = Attachment.objects.filter(
            tenant=document.tenant, content_type=content_type, object_id=document.id,
            category=rule.required_category, status=Attachment.Status.ACTIVE,
        ).exists()
        if not has_attachment:
            raise ValidationError(
                _("المستند يتطلب مرفق «%(category)s» لأنه يتجاوز %(amount)s.")
                % {"category": rule.get_required_category_display(), "amount": rule.min_amount_base}
            )


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
    _check_mandatory_attachments(document, doc_type, amount_base)

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


def _other_active_user_holds_role(tenant, role_id, exclude_user_id):
    from apps.accounts.models import User

    return User.objects.filter(tenant=tenant, is_active=True, roles__id=role_id).exclude(id=exclude_user_id).exists()


@transaction.atomic
def approve(document, user, doc_type, amount_base, request=None, emergency_reason=""):
    """3.15.9 segregation of duties: the creator can never approve
    their own document — except in a single-active-user tenant
    ("الوضع المبسّط"), where there is nobody else who could; that
    exemption is itself logged (3.15.1: "يُعفى تلقائيًا مع تسجيل
    ذلك"). Sprint 6.8 (decision 18, D4): a *multi*-user tenant where no
    OTHER active user currently holds the required role (checked right
    now, not cached) is a genuine deadlock otherwise — an Owner may
    break it with a mandatory `emergency_reason`, logged as
    `is_emergency_approval=True` in this same AuditLog entry (no
    permanent permission is ever granted)."""
    from apps.access.services import user_is_owner

    _lock(document)
    if document.status != STATUS_PENDING_APPROVAL:
        raise ValidationError(_("Only a pending-approval document can be approved."))

    rule = get_matching_rule(document.tenant, doc_type, amount_base)
    exempted = rule is not None and _is_single_active_user_tenant(document.tenant)
    is_emergency = False
    if rule is not None and not exempted:
        blocked = document.created_by_id == user.id or not user.roles.filter(id=rule.required_role_id).exists()
        if blocked:
            can_use_emergency = user_is_owner(user) and not _other_active_user_holds_role(
                document.tenant, rule.required_role_id, user.id
            )
            if not can_use_emergency:
                if document.created_by_id == user.id:
                    raise PermissionDenied(_("You cannot approve a document you created yourself."))
                raise PermissionDenied(_("You do not have the required role to approve this document."))
            if not emergency_reason:
                raise ValidationError(_("الاعتماد الاضطراري يشترط سببًا إلزاميًا."))
            is_emergency = True

    document.status = STATUS_APPROVED
    document.save(update_fields=["status"])
    after = None
    if exempted:
        after = {"single_user_tenant_exemption": True}
    elif is_emergency:
        after = {"is_emergency_approval": True, "emergency_reason": emergency_reason}
    _log(document, doc_type, user, "approved", after=after, request=request)
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
