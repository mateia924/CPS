"""Sprint 6.7 (docs/SYSTEM_ANALYSIS.md 3.9, sprint-6.md decision 13):
the real period-close checklist ("قائمة إقفال الفترة") — replaces
block 6.1's simplified close check (previous period closed + no
unposted document) with the full BLOCK/WARN/INFO list, and requires
explicit acknowledgment of every WARN before a period can close.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import FiscalPeriod
from .periods import _lock_year_if_all_periods_locked, _log_period_action, _previous_period


def _unposted_documents(tenant_id, start_date, end_date):
    """Decision 13's BLOCK #2 — every DRAFT/PENDING_APPROVAL/APPROVED
    document dated inside the period, with its own reference, across
    every document type this project has (invoices, vouchers, manual
    journal entries, opening balances)."""
    from apps.accounting.models import JournalEntry, OpeningBalanceEntry
    from apps.sales.models import Invoice
    from apps.vouchers.models import Voucher

    unposted = []
    for invoice in Invoice.objects.filter(
        tenant_id=tenant_id, issue_date__gte=start_date, issue_date__lte=end_date,
        status__in=[Invoice.Status.DRAFT, Invoice.Status.PENDING_APPROVAL, Invoice.Status.APPROVED],
    ):
        unposted.append({"type": "invoice", "id": str(invoice.id), "reference": invoice.number or str(_("(draft)"))})
    for voucher in Voucher.objects.filter(
        tenant_id=tenant_id, date__gte=start_date, date__lte=end_date,
        status__in=["draft", "pending_approval", "approved"],
    ):
        unposted.append({"type": "voucher", "id": str(voucher.id), "reference": voucher.number or str(_("(draft)"))})
    for entry in JournalEntry.objects.filter(
        tenant_id=tenant_id, date__gte=start_date, date__lte=end_date,
        status__in=["draft", "pending_approval", "approved"],
    ):
        unposted.append({"type": "journal_entry", "id": str(entry.id), "reference": entry.number or str(_("(draft)"))})
    for entry in OpeningBalanceEntry.objects.filter(
        tenant_id=tenant_id, opening_date__gte=start_date, opening_date__lte=end_date,
        status__in=[OpeningBalanceEntry.Status.DRAFT, OpeningBalanceEntry.Status.PENDING_APPROVAL],
    ):
        unposted.append({"type": "opening_balance", "id": str(entry.id), "reference": str(entry)})
    return unposted


def _depreciable_assets_without_schedule(tenant_id):
    """Decision 10: replaces the dead INFO placeholder — every active,
    depreciable asset with no depreciation schedule at all yet."""
    from apps.assets.models import Asset

    assets = Asset.objects.filter(
        tenant_id=tenant_id, is_active=True, is_depreciable=True,
        status=Asset.Status.ACTIVE, depreciation_entry__isnull=True,
    )
    return [{"id": str(a.id), "reference": f"{a.code} {a.name}"} for a in assets]


def _due_installments_not_generated(tenant_id, period):
    from .models import RecurringInstallment

    installments = RecurringInstallment.objects.filter(entry__tenant_id=tenant_id, period=period, status=RecurringInstallment.Status.DUE)
    return [
        {"id": str(i.id), "reference": f"{i.entry.number or i.entry.description} #{i.seq}"}
        for i in installments.select_related("entry")
    ]


def _bank_reconciliation_warnings(tenant, period):
    from apps.treasury.models import Bank
    from apps.treasury.reconciliation import reconciliation_report

    warnings = []
    for bank in Bank.objects.filter(tenant=tenant, is_active=True):
        report = reconciliation_report(tenant, bank, as_of=period.end_date)
        if report["difference"] != Decimal("0"):
            warnings.append(
                {
                    "level": "warn", "code": "bank_not_reconciled", "bank_id": str(bank.id), "bank_name": bank.name,
                    "message": str(
                        _("البنك «%(name)s» بفرق تسوية %(diff)s حتى نهاية الفترة.")
                        % {"name": bank.name, "diff": report["difference"]}
                    ),
                }
            )
    return warnings


def _posted_documents_without_attachment(tenant, period):
    from apps.accounting.models import JournalEntry
    from apps.attachments.models import Attachment
    from apps.sales.models import Invoice
    from apps.vouchers.models import Voucher

    def _has_attachment(app_label, model_name, object_id):
        content_type = _content_type(app_label, model_name)
        return Attachment.objects.filter(
            tenant=tenant, content_type=content_type, object_id=object_id, status=Attachment.Status.ACTIVE
        ).exists()

    missing = []
    for entry in JournalEntry.objects.filter(
        tenant=tenant, date__gte=period.start_date, date__lte=period.end_date,
        status__in=["posted", "reversed"],
    ):
        if not _has_attachment("accounting", "journalentry", entry.id):
            missing.append({"type": "journal_entry", "id": str(entry.id), "reference": entry.number})
    for invoice in Invoice.objects.filter(
        tenant=tenant, issue_date__gte=period.start_date, issue_date__lte=period.end_date,
        status__in=[Invoice.Status.ISSUED, Invoice.Status.PAID, Invoice.Status.CANCELLED],
    ):
        if not _has_attachment("sales", "invoice", invoice.id):
            missing.append({"type": "invoice", "id": str(invoice.id), "reference": invoice.number})
    for voucher in Voucher.objects.filter(
        tenant=tenant, date__gte=period.start_date, date__lte=period.end_date, status="posted",
    ):
        if not _has_attachment("vouchers", "voucher", voucher.id):
            missing.append({"type": "voucher", "id": str(voucher.id), "reference": voucher.number})
    return missing


def _legacy_duplicate_document_numbers(tenant_id):
    """Sprint 6.5.15 (UAT item 1): a tenant-wide, historical count — not
    period-scoped, since a flagged row's own date could be anywhere and
    the debt itself is permanent (grandfathered, never renumbered)."""
    from apps.accounting.models import JournalEntry
    from apps.sales.models import Invoice
    from apps.vouchers.models import Voucher

    return (
        JournalEntry.objects.filter(tenant_id=tenant_id, legacy_duplicate_number=True).count()
        + Voucher.objects.filter(tenant_id=tenant_id, legacy_duplicate_number=True).count()
        + Invoice.objects.filter(tenant_id=tenant_id, legacy_duplicate_number=True).count()
    )


_CONTENT_TYPE_CACHE = {}


def _content_type(app_label, model_name):
    from django.contrib.contenttypes.models import ContentType

    key = (app_label, model_name)
    if key not in _CONTENT_TYPE_CACHE:
        _CONTENT_TYPE_CACHE[key] = ContentType.objects.get_by_natural_key(app_label, model_name)
    return _CONTENT_TYPE_CACHE[key]


def period_checklist(period):
    """Decision 13: the full BLOCK/WARN/INFO list for one fiscal
    period, computed fresh every time — snapshotted by close_period
    only at the moment it actually closes."""
    tenant = period.fiscal_year.tenant
    items = []

    previous = _previous_period(period)
    if previous is not None and previous.status == FiscalPeriod.Status.OPEN:
        items.append(
            {
                "level": "block", "code": "previous_period_open",
                "message": str(_("الفترة السابقة (%(period)s) غير مقفلة.") % {"period": str(previous)}),
            }
        )

    unposted = _unposted_documents(tenant.id, period.start_date, period.end_date)
    if unposted:
        items.append(
            {
                "level": "block", "code": "unposted_documents",
                "message": str(_("توجد %(count)s مستندات غير مرحَّلة بتاريخ داخل الفترة.") % {"count": len(unposted)}),
                "references": unposted,
            }
        )

    due_installments = _due_installments_not_generated(tenant.id, period)
    if due_installments:
        items.append(
            {
                "level": "block", "code": "recurring_installments_due",
                "message": str(
                    _("توجد %(count)s أقساط دورية مستحقة في الفترة لم تُولَّد بعد.") % {"count": len(due_installments)}
                ),
                "references": due_installments,
            }
        )

    items.extend(_bank_reconciliation_warnings(tenant, period))

    missing_attachments = _posted_documents_without_attachment(tenant, period)
    if missing_attachments:
        items.append(
            {
                "level": "warn", "code": "posted_without_attachment",
                "message": str(
                    _("توجد %(count)s مستندات مرحَّلة في الفترة بلا مرفق.") % {"count": len(missing_attachments)}
                ),
                "references": missing_attachments,
            }
        )

    from apps.accounting.models import TaxPeriod

    tax_period = TaxPeriod.objects.filter(tenant=tenant, start__lte=period.end_date, end__gte=period.end_date).first()
    if tax_period is None or tax_period.status == TaxPeriod.Status.OPEN:
        items.append(
            {
                "level": "warn", "code": "tax_period_not_filed",
                "message": str(_("فترة الإقرار الضريبي المحتوية لنهاية الفترة ليست مُقدَّمة أو مسدَّدة.")),
            }
        )

    from apps.organization.models import LegalEntity

    unapproved_entities = list(
        LegalEntity.objects.filter(tenant=tenant, is_active=True, opening_approved_at__isnull=True).values_list("name", flat=True)
    )
    if unapproved_entities:
        items.append(
            {
                "level": "warn", "code": "opening_not_approved",
                "message": str(
                    _("الافتتاح غير معتمد لكيانات: %(names)s.") % {"names": "، ".join(unapproved_entities)}
                ),
            }
        )

    from .services import compute_trial_balance

    trial_balance = compute_trial_balance(tenant, date_from=period.start_date, date_to=period.end_date)
    items.append(
        {
            "level": "info", "code": "trial_balance_balanced",
            "message": str(
                _("ميزان المراجعة متوازن: مدين %(debit)s = دائن %(credit)s.")
                % {"debit": trial_balance["total_debit"], "credit": trial_balance["total_credit"]}
            ),
        }
    )
    depreciable_without_schedule = _depreciable_assets_without_schedule(tenant.id)
    if depreciable_without_schedule:
        items.append(
            {
                "level": "warn", "code": "depreciable_assets_without_schedule",
                "message": str(
                    _("توجد %(count)s أصول قابلة للإهلاك نشطة بلا جدول إهلاك.")
                    % {"count": len(depreciable_without_schedule)}
                ),
                "references": depreciable_without_schedule,
            }
        )

    from apps.assets.reconciliation import register_vs_ledger

    reconciliation = register_vs_ledger(tenant, as_of=period.end_date)
    if reconciliation["cost_diff"] != 0 or reconciliation["accum_diff"] != 0:
        items.append(
            {
                "level": "warn", "code": "asset_register_ledger_mismatch",
                "message": str(
                    _("سجل الأصول لا يطابق الدليل: فرق التكلفة %(cost_diff)s، فرق المجمّع %(accum_diff)s.")
                    % {"cost_diff": reconciliation["cost_diff"], "accum_diff": reconciliation["accum_diff"]}
                ),
            }
        )

    duplicate_numbers = _legacy_duplicate_document_numbers(tenant.id)
    if duplicate_numbers:
        items.append(
            {
                "level": "warn", "code": "legacy_duplicate_document_numbers",
                "message": str(_("أرقام مستندات مكررة تاريخية: %(count)s.") % {"count": duplicate_numbers}),
            }
        )

    return items


def close_period(period, user, note="", acknowledge_warnings=False):
    """Decision 13: replaces block 6.1's simplified check. Any BLOCK
    item → rejected outright; any WARN present without
    `acknowledge_warnings=True` → also rejected — the owner/accountant
    must have actually seen the checklist before closing."""
    if period.status != FiscalPeriod.Status.OPEN:
        raise ValidationError(str(_("لا يمكن إقفال إلا فترة مفتوحة.")))

    checklist = period_checklist(period)
    blocks = [item for item in checklist if item["level"] == "block"]
    if blocks:
        raise ValidationError({"blocks": [item["message"] for item in blocks]})

    warnings = [item for item in checklist if item["level"] == "warn"]
    if warnings and not acknowledge_warnings:
        raise ValidationError(
            {"warnings": [item["message"] for item in warnings], "detail": [str(_("توجد تحذيرات تحتاج إقرارًا قبل الإقفال."))]}
        )

    period.status = FiscalPeriod.Status.CLOSED
    period.closed_by = user
    period.closed_at = timezone.now()
    period.close_note = note
    period.close_snapshot = {"items": checklist, "acknowledged_warnings": acknowledge_warnings, "checked_at": period.closed_at.isoformat()}
    period.save(update_fields=["status", "closed_by", "closed_at", "close_note", "close_snapshot"])

    _log_period_action(period, user, "fiscal_period.closed", before_status="open", after_status="closed")
    _lock_year_if_all_periods_locked(period.fiscal_year)
    return period
