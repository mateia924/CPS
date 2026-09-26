"""Sprint 6.8 (decision 17): the daily pending-approvals digest —
one combined email per user, listing every document currently waiting
on their approval, same eligibility rule the inbox screen itself uses
(apps.approvals.services.list_pending_approvals)."""

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.utils.translation import gettext_lazy as _

DOC_TYPE_LABEL = {
    "journal_entry": _("قيد يدوي"),
    "invoice": _("فاتورة"),
    "voucher_receipt": _("سند قبض"),
    "voucher_payment": _("سند صرف"),
    "voucher_settlement": _("سند تسوية"),
    "iban_change": _("طلب تغيير IBAN"),
    "opening_balance": _("رصيد افتتاحي"),
    "recurring_entry": _("قيد دوري"),
    "asset_depreciation": _("جدول إهلاك أصل"),
    "asset_addition": _("إضافة على أصل"),
    "asset_disposal": _("استبعاد أصل"),
}

DOC_TYPE_PATH = {
    "journal_entry": "accounting/journal-entries",
    "invoice": "invoices",
    "voucher_receipt": "treasury/vouchers",
    "voucher_payment": "treasury/vouchers",
    "voucher_settlement": "treasury/vouchers",
    "opening_balance": "accounting/opening-balances",
    "recurring_entry": "accounting/recurring-entries",
}


def _item_link(item):
    path = DOC_TYPE_PATH.get(item["doc_type"])
    if path is None:
        # iban_change has no dedicated detail screen yet — link to the
        # general inbox, where it's still listed and actionable.
        return f"{settings.FRONTEND_BASE_URL}/dashboard/approvals"
    return f"{settings.FRONTEND_BASE_URL}/dashboard/{path}/{item['id']}"


def _digest_body(items):
    lines = [str(_("لديك %(count)s مستندات بانتظار اعتمادك:") % {"count": len(items)}), ""]
    for item in items:
        label = DOC_TYPE_LABEL.get(item["doc_type"], item["doc_type"])
        lines.append(
            f"- {label} {item['number'] or ''} — {item['description']} — "
            f"{item['amount_base']} — {item['date']}\n  {_item_link(item)}"
        )
    return "\n".join(str(line) for line in lines)


@shared_task
def send_pending_approvals_digest():
    """Celery beat, daily 05:00 UTC. Skips a user with no email or
    `notify_approvals_email=False` — never sends to either."""
    from apps.accounts.models import User
    from apps.approvals.services import list_pending_approvals

    sent = 0
    users = User.objects.filter(is_active=True, notify_approvals_email=True).exclude(email="")
    for user in users:
        items = list_pending_approvals(user)
        if not items:
            continue
        send_mail(
            subject=str(_("مستندات بانتظار اعتمادك (%(count)s)") % {"count": len(items)}),
            message=_digest_body(items),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
        )
        sent += 1
    return sent
