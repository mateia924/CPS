import datetime
import logging
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import ExchangeRate

logger = logging.getLogger(__name__)

RATE_QUANT = Decimal("0.00000001")
STALE_RATE_DAYS = 7
# CFO_REVIEW_1 C10 (block 5.5.0): a party whose IBAN changed within
# this many days of a payment voucher gets a warning, not a block.
IBAN_CHANGE_RECENT_DAYS = 30


class ExchangeRateNotFound(Exception):
    """Raised by get_rate below; callers turn this into a 400 with the
    Arabic message attached."""

    def __init__(self, message):
        self.message = message
        super().__init__(message)


class TreasuryConflictError(Exception):
    """Raised for a genuine state conflict (not a malformed request) —
    callers turn this into a 409, same distinction
    apps.sales.views.partial_update already draws between 400 (bad
    input) and 409 (the request is fine, the document's current state
    isn't)."""

    def __init__(self, message):
        self.message = message
        super().__init__(message)


def _find_rate_row(tenant, from_currency, to_currency, date):
    """CFO_REVIEW_1 C14: the direct pair first; if it's never been
    recorded, fall back to the reverse pair's most recent row and let
    the caller invert it (1/rate) — returns (row, inverted: bool) or
    (None, False). Logged (not raised) since this is an expected,
    correct fallback, not an error."""
    row = (
        ExchangeRate.objects.filter(
            tenant=tenant, from_currency=from_currency, to_currency=to_currency, date__lte=date
        )
        .order_by("-date")
        .first()
    )
    if row is not None:
        return row, False

    reverse_row = (
        ExchangeRate.objects.filter(
            tenant=tenant, from_currency=to_currency, to_currency=from_currency, date__lte=date
        )
        .order_by("-date")
        .first()
    )
    if reverse_row is not None:
        logger.info(
            "get_rate: no %s->%s rate for tenant %s as of %s — inferred from the recorded %s->%s rate (1/rate).",
            from_currency, to_currency, tenant.id, date, to_currency, from_currency,
        )
        return reverse_row, True
    return None, False


def get_rate(tenant, from_currency, to_currency, date):
    """Sprint 4.2 (docs/SYSTEM_ANALYSIS.md 3.15.3): the most recent rate
    with date <= the requested date — never a future rate, and never an
    average/interpolation. Same currency is always 1 (no DB lookup, no
    row needed). CFO_REVIEW_1 C14: infers the inverse (1/rate) from the
    reverse pair when the direct pair was never recorded."""
    if from_currency == to_currency:
        return Decimal("1")

    row, inverted = _find_rate_row(tenant, from_currency, to_currency, date)
    if row is None:
        raise ExchangeRateNotFound(
            _("لا يوجد سعر صرف مسجَّل من %(from)s إلى %(to)s بتاريخ %(date)s أو قبله.")
            % {"from": from_currency, "to": to_currency, "date": date}
        )
    if inverted:
        return (Decimal("1") / row.rate).quantize(RATE_QUANT, rounding=ROUND_HALF_UP)
    return row.rate


def get_rate_with_warnings(tenant, from_currency, to_currency, date):
    """Same resolution as get_rate, plus a `warnings[]` entry when the
    resolved rate's own recorded date is more than STALE_RATE_DAYS
    before the requested date (CFO_REVIEW_1 C14) — for callers that
    already surface a warnings list to the user (e.g. vouchers)."""
    if from_currency == to_currency:
        return Decimal("1"), []

    row, inverted = _find_rate_row(tenant, from_currency, to_currency, date)
    if row is None:
        raise ExchangeRateNotFound(
            _("لا يوجد سعر صرف مسجَّل من %(from)s إلى %(to)s بتاريخ %(date)s أو قبله.")
            % {"from": from_currency, "to": to_currency, "date": date}
        )
    rate = (Decimal("1") / row.rate).quantize(RATE_QUANT, rounding=ROUND_HALF_UP) if inverted else row.rate
    warnings = []
    age_days = (date - row.date).days
    if age_days > STALE_RATE_DAYS:
        warnings.append(
            str(
                _("سعر الصرف المستخدَم أقدم من %(days)s أيام (بتاريخ %(rate_date)s) — تحقّق منه.")
                % {"days": age_days, "rate_date": row.date}
            )
        )
    return rate, warnings


def treasury_balance(tenant, kind, treasury_id, as_of=None):
    """Sprint 5.3/5.4: current running balance of a Bank/CashBox/
    Custody's gl_account, from POSTED/REVERSED journal lines only
    (apps.accounting.services.REPORTABLE_STATUSES) — the single service
    `ledger_lines()` (5.7) will later be built on the same querying
    principle for the full statements. Returns both the base-currency
    balance and the account's own currency balance (debit_fc/credit_fc
    — always in one consistent currency per account, since every
    voucher's currency is pinned to its treasury account's own
    currency by construction, decision 4).
    """
    from django.db.models import Sum

    from apps.accounting.services import REPORTABLE_STATUSES
    from apps.treasury.models import Bank, CashBox, Custody

    model = {"bank": Bank, "cash_box": CashBox, "custody": Custody}[kind]
    instance = model.objects.get(tenant=tenant, id=treasury_id)
    account = instance.gl_account
    if account is None:
        return {"base": Decimal("0"), "fc": Decimal("0")}

    lines = account.journal_lines.filter(entry__tenant=tenant, entry__status__in=REPORTABLE_STATUSES)
    if as_of is not None:
        lines = lines.filter(entry__date__lte=as_of)
    totals = lines.aggregate(
        debit=Sum("debit"), credit=Sum("credit"), debit_fc=Sum("debit_fc"), credit_fc=Sum("credit_fc")
    )
    # Treasury accounts are always ASSET/debit-normal.
    base = (totals["debit"] or Decimal("0")) - (totals["credit"] or Decimal("0"))
    fc = (totals["debit_fc"] or Decimal("0")) - (totals["credit_fc"] or Decimal("0"))
    return {"base": base, "fc": fc}


# ---------------------------------------------------------------------
# IBAN change requests (sprint 5.5, block 5.5.0 — CFO_REVIEW_1 C10)
# ---------------------------------------------------------------------

IBAN_CHANGE_DOC_TYPE = "iban_change"


def _iban_change_target_model(target_type):
    from apps.parties.models import Party

    from .models import Bank

    model = {"bank": Bank, "party": Party}.get(target_type)
    if model is None:
        raise ValidationError({"target_type": [_("Unknown IBAN change target type.")]})
    return model


def _resolve_iban_change_target(tenant, target_type, target_id):
    model = _iban_change_target_model(target_type)
    try:
        return model.objects.get(tenant=tenant, id=target_id)
    except model.DoesNotExist:
        raise ValidationError({"target_id": [_("Target record not found.")]})


@transaction.atomic
def create_iban_change_request(tenant, user, target_type, target_id, new_iban, reason):
    from django.contrib.contenttypes.models import ContentType

    from .models import IbanChangeRequest

    target = _resolve_iban_change_target(tenant, target_type, target_id)
    if not reason:
        raise ValidationError({"reason": [_("A reason is required.")]})
    if new_iban == target.iban:
        raise ValidationError({"new_iban": [_("New IBAN is identical to the current one.")]})

    content_type = ContentType.objects.get_for_model(type(target))
    has_pending = IbanChangeRequest.objects.filter(
        tenant=tenant, content_type=content_type, object_id=target.id,
        status__in=[IbanChangeRequest.Status.DRAFT, IbanChangeRequest.Status.PENDING_APPROVAL],
    ).exists()
    if has_pending:
        raise ValidationError(
            {"detail": [_("There is already a pending IBAN change request for this target.")]}
        )

    return IbanChangeRequest.objects.create(
        tenant=tenant, content_type=content_type, object_id=target.id,
        old_iban=target.iban, new_iban=new_iban, reason=reason, created_by=user,
    )


def _apply_iban_change(iban_request, user, request=None):
    from apps.platform.models import AuditLog
    from apps.platform.services import log_action

    target = iban_request.target
    before = {"iban": target.iban}
    target.iban = iban_request.new_iban
    target.save(update_fields=["iban"])
    iban_request.decided_by = user
    iban_request.decided_at = timezone.now()
    iban_request.save(update_fields=["decided_by", "decided_at"])
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER, actor_id=user.id if user else None,
        action="iban_change_request.applied", target_type=iban_request.content_type.model,
        target_id=iban_request.object_id, tenant_id=iban_request.tenant_id,
        before=before, after={"iban": target.iban}, request=request,
    )


@transaction.atomic
def submit_iban_change_request(iban_request, user, request=None):
    from apps.approvals.services import submit_for_approval

    from .models import IbanChangeRequest

    if iban_request.status != IbanChangeRequest.Status.DRAFT:
        raise ValidationError({"detail": [_("Only a draft request can be submitted.")]})
    if not _has_active_attachment(iban_request):
        raise ValidationError(
            {"detail": [_("An IBAN letter attachment is required before submitting for approval.")]}
        )

    auto_approved = submit_for_approval(
        iban_request, user, IBAN_CHANGE_DOC_TYPE, Decimal("0"), request=request
    )
    if auto_approved:
        _apply_iban_change(iban_request, user, request=request)
    return iban_request


def _has_active_attachment(iban_request):
    from django.contrib.contenttypes.models import ContentType

    from apps.attachments.models import Attachment

    content_type = ContentType.objects.get_for_model(type(iban_request))
    return Attachment.objects.filter(
        tenant=iban_request.tenant_id, content_type=content_type, object_id=iban_request.id,
        status=Attachment.Status.ACTIVE,
    ).exists()


@transaction.atomic
def approve_iban_change_request(iban_request, user, request=None):
    from apps.approvals.services import approve as approvals_approve

    approvals_approve(iban_request, user, IBAN_CHANGE_DOC_TYPE, Decimal("0"), request=request)
    _apply_iban_change(iban_request, user, request=request)
    return iban_request


def reject_iban_change_request(iban_request, user, reason, request=None):
    from apps.approvals.services import reject as approvals_reject

    approvals_reject(iban_request, user, IBAN_CHANGE_DOC_TYPE, reason, request=request)
    return iban_request


def withdraw_iban_change_request(iban_request, user, request=None):
    from apps.approvals.services import withdraw as approvals_withdraw

    approvals_withdraw(iban_request, user, IBAN_CHANGE_DOC_TYPE, request=request)
    return iban_request


# ---------------------------------------------------------------------
# Bank statement import (sprint 5.5, block 5.5.1)
# ---------------------------------------------------------------------


@transaction.atomic
def import_bank_statement(
    tenant, user, bank, file_obj, import_format, period_start, period_end,
    opening_balance, closing_balance, currency, column_mapping=None, request=None,
):
    from apps.attachments.services import StorageQuotaExceeded as _StorageQuotaExceeded
    from apps.attachments.services import (
        check_file_size,
        check_storage_limit,
        compute_sha256,
        create_attachment,
        detect_mime_type,
    )

    from .models import Bank, BankStatement, BankStatementLine
    from .statement_parsers import parse_statement_file

    if currency != bank.currency:
        raise ValidationError(
            {"currency": [_("Statement currency must match the bank account's own currency.")]}
        )
    if period_end < period_start:
        raise ValidationError({"period_end": [_("Period end cannot be before period start.")]})

    file_obj.seek(0)
    sha256 = compute_sha256(file_obj)
    if BankStatement.objects.filter(tenant=tenant, bank=bank, file_sha256=sha256).exists():
        raise TreasuryConflictError(_("This exact statement file has already been imported for this bank."))
    if BankStatement.objects.filter(
        tenant=tenant, bank=bank, period_start__lte=period_end, period_end__gte=period_start
    ).exists():
        raise TreasuryConflictError(_("This statement's period overlaps an already-imported statement."))

    file_obj.seek(0)
    lines, mt940_meta = parse_statement_file(file_obj, import_format, column_mapping)

    warnings = []
    previous = (
        BankStatement.objects.filter(tenant=tenant, bank=bank, period_end__lt=period_start)
        .order_by("-period_end")
        .first()
    )
    if previous is not None and previous.closing_balance != opening_balance:
        warnings.append(
            str(
                _("Opening balance (%(opening)s) does not match the previous statement's closing balance (%(prev)s).")
                % {"opening": opening_balance, "prev": previous.closing_balance}
            )
        )
    if mt940_meta:
        file_opening = mt940_meta.get("final_opening_balance")
        file_closing = mt940_meta.get("final_closing_balance")
        if file_opening is not None and file_opening.amount.amount != opening_balance:
            warnings.append(
                str(_("MT940 file's own opening balance (%s) differs from the value entered.") % file_opening.amount.amount)
            )
        if file_closing is not None and file_closing.amount.amount != closing_balance:
            warnings.append(
                str(_("MT940 file's own closing balance (%s) differs from the value entered.") % file_closing.amount.amount)
            )

    file_obj.seek(0)
    check_file_size(tenant, file_obj.size)
    try:
        check_storage_limit(tenant, file_obj.size)
    except _StorageQuotaExceeded as exc:
        raise ValidationError({"file": [str(exc.message)]})
    mime_type = detect_mime_type(file_obj, file_obj.name)

    statement = BankStatement.objects.create(
        tenant=tenant, bank=bank, period_start=period_start, period_end=period_end,
        currency=currency, opening_balance=opening_balance, closing_balance=closing_balance,
        import_format=import_format, file_sha256=sha256, line_count=len(lines), imported_by=user,
    )
    BankStatementLine.objects.bulk_create(
        BankStatementLine(
            tenant=tenant, statement=statement, line_no=index, date=line.date, amount=line.amount,
            description=line.description, reference=line.reference,
        )
        for index, line in enumerate(lines, start=1)
    )

    if import_format in ("csv", "xlsx") and column_mapping:
        Bank.objects.filter(tenant=tenant, id=bank.id).update(import_column_mapping=column_mapping)

    from django.contrib.contenttypes.models import ContentType

    from apps.attachments.models import Attachment

    file_obj.seek(0)
    create_attachment(
        tenant, ContentType.objects.get_for_model(BankStatement), statement, file_obj, mime_type, sha256,
        Attachment.Category.BANK_STATEMENT, user,
        description=f"{import_format} statement import", request=request,
    )

    # Auto-matching wiring lands in block 5.5.2
    # (apps.treasury.reconciliation.auto_match_statement) — every line
    # starts UNMATCHED until then.
    auto_matched = statement.lines.filter(status=BankStatementLine.Status.MATCHED).count()
    unmatched = statement.lines.exclude(status=BankStatementLine.Status.MATCHED).count()
    return statement, auto_matched, unmatched, warnings


def check_iban_change_guard(party):
    """CFO_REVIEW_1 C10's payment guard (decision 6): called from
    apps.vouchers.services for a PAYMENT voucher with a party. Raises
    TreasuryConflictError (-> 409) if a change request is currently
    pending for this party; otherwise returns a warnings[] list (empty,
    or one entry if the IBAN changed recently)."""
    from django.contrib.contenttypes.models import ContentType

    from apps.parties.models import Party

    from .models import IbanChangeRequest

    if party is None:
        return []
    content_type = ContentType.objects.get_for_model(Party)
    pending = IbanChangeRequest.objects.filter(
        content_type=content_type, object_id=party.id,
        status=IbanChangeRequest.Status.PENDING_APPROVAL,
    ).exists()
    if pending:
        raise TreasuryConflictError(
            _("There is a pending IBAN change request for this party — resolve it before paying.")
        )
    cutoff = timezone.now() - datetime.timedelta(days=IBAN_CHANGE_RECENT_DAYS)
    recent = (
        IbanChangeRequest.objects.filter(
            content_type=content_type, object_id=party.id,
            status=IbanChangeRequest.Status.APPROVED, decided_at__gte=cutoff,
        )
        .order_by("-decided_at")
        .first()
    )
    if recent is None:
        return []
    return [
        str(
            _("This party's IBAN was changed on %(date)s (approved by an IBAN change request) — verify before paying.")
            % {"date": recent.decided_at.date()}
        )
    ]
