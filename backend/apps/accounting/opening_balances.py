"""Sprint 6.3 (docs/SYSTEM_ANALYSIS.md 3.10/3.16.3, sprint-6.md decisions
5-8): opening balances. One INITIAL document per legal entity, any
number of ADJUSTMENT documents afterward; a draft may be unbalanced, a
readiness report surfaces BLOCK/WARN/INFO items on demand, `submit`
requires balance, and `approve` requires a written attestation (>= 20
characters) from the tenant's Owner (the fixed, non-deletable
`ApprovalRule` seeded by approvals/migrations/0007) before posting a
POSTED `JournalEntry(is_opening=True)` straight from the system path —
never a manual one, so the usual control-account posting restriction
does not apply here. That posted entry can never be reversed
(`OpeningEntryReversalRejected`, 409); the only correction is a new
ADJUSTMENT document with its own balanced difference lines.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.numbering.services import next_document_number
from apps.platform.models import AuditLog
from apps.platform.services import log_action

from .models import Account, JournalEntry, JournalLine, OpeningBalanceEntry, OpeningBalanceLine
from .periods import assert_open_period
from .services import (
    _SYSTEM_KEY_BY_PARTY_ROLE,
    CENTS,
    REPORTABLE_STATUSES,
    get_or_create_party_role_account,
)

DOC_TYPE = "opening_balance"

# decision 6: a party's control account (the CUSTOMERS/SUPPLIERS/
# EMPLOYEES/AFFILIATES parent in the chart) is never chosen directly —
# the party + role must be given instead and the sub-ledger account
# resolved the same way 4.3 already resolves it for every other
# document. Derived from the same canonical mapping 4.3 uses rather
# than a second hardcoded copy of it.
_PARTY_ROLE_CONTROL_KEYS = set(_SYSTEM_KEY_BY_PARTY_ROLE.values())

# decision 6: "الحساب ورقة نشطة من أنواع الميزانية فقط" — an opening
# balance never carries income/expense.
_ALLOWED_LINE_TYPES = {Account.Type.ASSET, Account.Type.LIABILITY, Account.Type.EQUITY}


class OpeningBalanceLocked(Exception):
    """Raised when attempting to change an already-approved opening
    balance's lines — the view maps this to 409 (decision 8: "المستند
    وقيده غير قابلين للتعديل" after approval). Correction is always a
    new ADJUSTMENT document, never an edit of this one."""


def _first_fiscal_year_start(tenant):
    from .models import FiscalYear

    year = FiscalYear.objects.filter(tenant=tenant).order_by("start_date").first()
    if year is None:
        raise ValidationError(_("لا توجد سنة مالية بعد لهذا المستأجر — أنشئ واحدة قبل إنشاء مستند افتتاح."))
    return year.start_date


def _resolve_opening_date(tenant, legal_entity, kind):
    """Decision 5: INITIAL's date is fixed (the tenant's first fiscal
    year's own start), never a caller-supplied value. ADJUSTMENT reuses
    the INITIAL's own opening_date if its period is still open,
    otherwise today."""
    if kind == OpeningBalanceEntry.Kind.INITIAL:
        return _first_fiscal_year_start(tenant)

    initial = (
        OpeningBalanceEntry.objects.filter(
            tenant=tenant, legal_entity=legal_entity, kind=OpeningBalanceEntry.Kind.INITIAL
        )
        .exclude(status=OpeningBalanceEntry.Status.REJECTED)
        .first()
    )
    if initial is None:
        raise ValidationError(
            _("لا يمكن إنشاء مستند تعديل قبل وجود مستند الافتتاح الأولي لهذا الكيان.")
        )
    try:
        assert_open_period(tenant, initial.opening_date)
        return initial.opening_date
    except ValidationError:
        return timezone.localdate()


def _resolve_line_account(spec):
    party = spec.get("party")
    party_role = spec.get("party_role") or ""
    if party is not None:
        if not party_role:
            raise ValidationError(_("اختيار طرف لسطر الافتتاح يشترط تحديد دوره أيضًا."))
        account = get_or_create_party_role_account(party, party_role)
        if account is None:
            raise ValidationError(
                _("لا يوجد حساب رقابة لهذا الدور (%(role)s) في دليل حسابات هذا المستأجر.") % {"role": party_role}
            )
        return account, party, party_role

    account = spec.get("account")
    if account is None:
        raise ValidationError(_("كل سطر افتتاح يحتاج حسابًا أو طرفًا ودوره."))
    if account.system_key in _PARTY_ROLE_CONTROL_KEYS:
        raise ValidationError(
            _("لا يمكن اختيار حساب الرقابة «%(name)s» مباشرة — اختر الطرف ودوره بدلًا من ذلك.")
            % {"name": account.name}
        )
    return account, None, ""


def _build_opening_line(tenant, base_currency, opening_date, spec, warnings):
    account, party, party_role = _resolve_line_account(spec)

    if not account.can_post:
        raise ValidationError(
            _("لا يمكن الترحيل على الحساب %(code)s: إما أنه حساب أب له فروع أو أن الترحيل عليه معطّل.")
            % {"code": account.code}
        )
    if account.type not in _ALLOWED_LINE_TYPES:
        raise ValidationError(
            _(
                "سطر الافتتاح على الحساب %(code)s غير مسموح: الأرصدة الافتتاحية تقتصر على "
                "حسابات الميزانية (أصول/خصوم/حقوق ملكية)، لا على الإيرادات أو المصروفات."
            )
            % {"code": account.code}
        )

    currency = spec.get("currency") or base_currency
    debit_fc = spec.get("debit_fc") or Decimal("0")
    credit_fc = spec.get("credit_fc") or Decimal("0")

    if currency == base_currency:
        exchange_rate = Decimal("1")
        debit_base, credit_base = debit_fc, credit_fc
    else:
        exchange_rate = spec.get("exchange_rate")
        if exchange_rate is None:
            from apps.treasury.services import get_rate_with_warnings

            exchange_rate, rate_warnings = get_rate_with_warnings(tenant, currency, base_currency, opening_date)
            warnings.extend(rate_warnings)
        debit_base = (debit_fc * exchange_rate).quantize(CENTS, rounding=ROUND_HALF_UP)
        credit_base = (credit_fc * exchange_rate).quantize(CENTS, rounding=ROUND_HALF_UP)

    open_items = spec.get("open_items") or None
    if open_items:
        items_total = sum((Decimal(str(item["amount_fc"])) for item in open_items), Decimal("0"))
        line_amount = debit_fc or credit_fc
        if items_total != line_amount:
            raise ValidationError(
                _("مجموع البنود المفتوحة (%(items)s) لا يساوي مبلغ السطر (%(amount)s).")
                % {"items": items_total, "amount": line_amount}
            )

    return OpeningBalanceLine(
        account=account,
        party=party,
        party_role=party_role,
        cost_center=spec.get("cost_center"),
        currency=currency,
        exchange_rate=exchange_rate,
        debit_fc=debit_fc,
        credit_fc=credit_fc,
        debit_base=debit_base,
        credit_base=credit_base,
        open_items=open_items,
        notes=spec.get("notes", ""),
    )


@transaction.atomic
def create_opening_balance_entry(tenant, user, legal_entity, kind, line_specs, request=None):
    if kind == OpeningBalanceEntry.Kind.INITIAL:
        exists = (
            OpeningBalanceEntry.objects.filter(
                tenant=tenant, legal_entity=legal_entity, kind=OpeningBalanceEntry.Kind.INITIAL
            )
            .exclude(status=OpeningBalanceEntry.Status.REJECTED)
            .exists()
        )
        if exists:
            raise ValidationError(_("يوجد بالفعل مستند افتتاح أولي لهذا الكيان القانوني."))

    opening_date = _resolve_opening_date(tenant, legal_entity, kind)
    entry = OpeningBalanceEntry.objects.create(
        tenant=tenant, legal_entity=legal_entity, kind=kind, opening_date=opening_date, prepared_by=user,
    )
    warnings = []
    lines = [
        _build_opening_line(tenant, legal_entity.base_currency, opening_date, spec, warnings)
        for spec in line_specs
    ]
    for line in lines:
        line.entry = entry
    OpeningBalanceLine.objects.bulk_create(lines)

    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER, actor_id=user.id, action="opening_balance.created",
        target_type="opening_balance", target_id=entry.id, tenant_id=tenant.id,
        after={"kind": kind, "legal_entity": str(legal_entity.id)}, request=request,
    )
    return entry, warnings


@transaction.atomic
def replace_opening_balance_lines(entry, line_specs):
    """Full replace of a still-DRAFT entry's line set — the screen's
    own running table (add/remove/edit before submit) calls this on
    every save, same "just re-derive it" approach as build_journal_
    lines_with_fx_rounding's caller."""
    if entry.status == OpeningBalanceEntry.Status.APPROVED:
        raise OpeningBalanceLocked(str(_("تم اعتماد هذا المستند ولم يعد قابلاً للتعديل.")))
    if entry.status != OpeningBalanceEntry.Status.DRAFT:
        raise ValidationError(_("لا يمكن تعديل سطور مستند إلا وهو في حالة مسودة."))

    warnings = []
    lines = [
        _build_opening_line(entry.tenant, entry.legal_entity.base_currency, entry.opening_date, spec, warnings)
        for spec in line_specs
    ]
    for line in lines:
        line.entry = entry
    entry.lines.all().delete()
    OpeningBalanceLine.objects.bulk_create(lines)
    return warnings


def readiness_report(entry):
    """Decision 7: BLOCK/WARN/INFO items, computed on demand and
    snapshotted (by the caller) at submit and at approve."""
    items = []
    lines = list(entry.lines.select_related("account", "party"))

    debit_total = sum((line.debit_base for line in lines), Decimal("0"))
    credit_total = sum((line.credit_base for line in lines), Decimal("0"))
    if debit_total != credit_total:
        items.append(
            {
                "level": "block",
                "code": "unbalanced",
                "message": str(
                    _("غير متوازن: إجمالي المدين %(debit)s لا يساوي إجمالي الدائن %(credit)s.")
                    % {"debit": debit_total, "credit": credit_total}
                ),
            }
        )

    try:
        assert_open_period(entry.tenant, entry.opening_date)
    except ValidationError as exc:
        message = exc.messages[0] if hasattr(exc, "messages") else str(exc)
        items.append({"level": "block", "code": "period_not_open", "message": str(message)})

    for line in lines:
        if line.party_id and not line.open_items:
            items.append(
                {
                    "level": "warn",
                    "code": "party_line_no_open_items",
                    "message": str(
                        _("سطر الطرف «%(name)s» بلا تفصيل بنود مفتوحة.") % {"name": line.party.name}
                    ),
                }
            )

    from apps.attachments.models import Attachment
    from apps.treasury.models import Bank, CashBox

    treasury_account_ids = set(
        Bank.objects.filter(tenant=entry.tenant, gl_account_id__isnull=False).values_list(
            "gl_account_id", flat=True
        )
    ) | set(
        CashBox.objects.filter(tenant=entry.tenant, gl_account_id__isnull=False).values_list(
            "gl_account_id", flat=True
        )
    )
    if any(line.account_id in treasury_account_ids for line in lines):
        has_bank_attachment = Attachment.objects.filter(
            tenant=entry.tenant,
            content_type__app_label="accounting",
            content_type__model="openingbalanceentry",
            object_id=entry.id,
            category__in=[Attachment.Category.BANK_STATEMENT, Attachment.Category.BANK_LETTER],
            status=Attachment.Status.ACTIVE,
        ).exists()
        if not has_bank_attachment:
            items.append(
                {
                    "level": "warn",
                    "code": "treasury_line_no_attachment",
                    "message": str(_("سطر بنك/صندوق بلا مرفق كشف أو خطاب بنكي على المستند.")),
                }
            )

    for line in lines:
        if line.account.type == Account.Type.ASSET and line.credit_base > line.debit_base:
            items.append(
                {
                    "level": "warn",
                    "code": "reversed_balance",
                    "message": str(
                        _("الحساب %(code)s (أصل) برصيد دائن — طبيعة معكوسة.") % {"code": line.account.code}
                    ),
                }
            )
        elif (
            line.account.type in (Account.Type.LIABILITY, Account.Type.EQUITY)
            and line.debit_base > line.credit_base
        ):
            items.append(
                {
                    "level": "warn",
                    "code": "reversed_balance",
                    "message": str(
                        _("الحساب %(code)s (خصم/حقوق ملكية) برصيد مدين — طبيعة معكوسة.")
                        % {"code": line.account.code}
                    ),
                }
            )

    if any(line.account.system_key == "OPENING_BALANCE" for line in lines):
        items.append(
            {
                "level": "warn",
                "code": "opening_balance_account_used",
                "message": str(_("يوجد رصيد على حساب فرق الافتتاح — يحتاج تسوية لاحقًا.")),
            }
        )

    earlier_exists = JournalEntry.objects.filter(
        tenant=entry.tenant, legal_entity=entry.legal_entity, status__in=REPORTABLE_STATUSES,
        date__lt=entry.opening_date, is_opening=False,
    ).exists()
    if earlier_exists:
        items.append(
            {
                "level": "warn",
                "code": "documents_before_opening",
                "message": str(_("توجد مستندات مرحَّلة بتاريخ يسبق تاريخ الافتتاح.")),
            }
        )

    items.append(
        {
            "level": "info",
            "code": "inventory_not_enabled",
            "message": str(_("المخزون الافتتاحي غير مفعَّل — سبرنت 7.")),
        }
    )
    return items


@transaction.atomic
def submit_opening_balance(entry, user, request=None):
    if entry.status != OpeningBalanceEntry.Status.DRAFT:
        raise ValidationError(_("لا يمكن إرسال مستند إلا وهو في حالة مسودة."))

    lines = list(entry.lines.all())
    debit_total = sum((line.debit_base for line in lines), Decimal("0"))
    credit_total = sum((line.credit_base for line in lines), Decimal("0"))
    if debit_total != credit_total:
        raise ValidationError(
            _("لا يمكن إرسال مستند افتتاح غير متوازن — الفرق %(diff)s.") % {"diff": abs(debit_total - credit_total)}
        )

    entry.readiness_snapshot = readiness_report(entry)
    entry.save(update_fields=["readiness_snapshot"])

    from apps.approvals.services import submit_for_approval

    auto_approved = submit_for_approval(entry, user, DOC_TYPE, debit_total, request=request)
    if auto_approved:
        # decision 8's fixed rule (min_amount=0, required_role=Owner) is
        # always seeded, so get_matching_rule never actually returns
        # None for this doc_type — this is a defensive fallback only,
        # never expected to run in practice.
        _finish_approval(entry, user, request=request)
    return entry


def withdraw_opening_balance(entry, user, request=None):
    from apps.approvals.services import withdraw as approvals_withdraw

    return approvals_withdraw(entry, user, DOC_TYPE, request=request)


@transaction.atomic
def reject_opening_balance(entry, user, reason, request=None):
    """Unlike apps.approvals.services.reject() (which bounces every
    other document type back to DRAFT), decision 5 gives opening
    balances their own terminal REJECTED status — so this is a small,
    self-contained transition rather than a call into that shared
    function."""
    locked = OpeningBalanceEntry.objects.select_for_update().get(pk=entry.pk)
    if locked.status != OpeningBalanceEntry.Status.PENDING_APPROVAL:
        raise ValidationError(_("لا يمكن رفض مستند إلا وهو بانتظار الاعتماد."))
    if not reason:
        raise ValidationError(_("رفض مستند الافتتاح يشترط سببًا."))

    entry.status = OpeningBalanceEntry.Status.REJECTED
    entry.save(update_fields=["status"])
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER, actor_id=user.id, action="opening_balance.rejected",
        target_type="opening_balance", target_id=entry.id, tenant_id=entry.tenant_id,
        after={"reason": reason}, request=request,
    )
    return entry


@transaction.atomic
def approve_opening_balance(entry, user, attestation_text, request=None):
    if not attestation_text or len(attestation_text.strip()) < 20:
        raise ValidationError(_("الاعتماد يشترط إقرارًا كتابيًا لا يقل عن 20 حرفًا."))

    from apps.approvals.services import approve as approvals_approve

    debit_total = sum((line.debit_base for line in entry.lines.all()), Decimal("0"))
    approvals_approve(entry, user, DOC_TYPE, debit_total, request=request)

    entry.attestation_text = attestation_text
    entry.save(update_fields=["attestation_text"])
    _finish_approval(entry, user, request=request)

    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER, actor_id=user.id, action="opening_balance.approved",
        target_type="opening_balance", target_id=entry.id, tenant_id=entry.tenant_id,
        after={"attestation_text": attestation_text}, request=request,
    )
    return entry


def _finish_approval(entry, user, request=None):
    """Shared tail of submit's defensive auto-approve fallback and the
    real approve() path: snapshot readiness, post the JournalEntry,
    stamp the entity/tenant "opening approved" markers (decision 8)."""
    entry.readiness_snapshot = readiness_report(entry)
    entry.approved_by = user
    entry.approved_at = timezone.now()
    entry.save(update_fields=["readiness_snapshot", "approved_by", "approved_at"])

    journal_entry = _post_opening_balance(entry, user)
    entry.journal_entry = journal_entry
    entry.save(update_fields=["journal_entry"])

    if entry.kind == OpeningBalanceEntry.Kind.INITIAL:
        entry.legal_entity.opening_approved_at = entry.approved_at
        entry.legal_entity.save(update_fields=["opening_approved_at"])

    _maybe_mark_tenant_opening_balances_approved(entry.tenant)


def _post_opening_balance(entry, user):
    assert_open_period(entry.tenant, entry.opening_date)
    lines = list(entry.lines.select_related("account", "cost_center"))

    journal_entry = JournalEntry.objects.create(
        tenant=entry.tenant,
        legal_entity=entry.legal_entity,
        date=entry.opening_date,
        memo=str(_("رصيد افتتاحي") if entry.kind == OpeningBalanceEntry.Kind.INITIAL else _("تعديل رصيد افتتاحي")),
        number=next_document_number(entry.tenant, "journal_entry", entry.legal_entity, entry.opening_date),
        status=JournalEntry.Status.POSTED,
        created_by=user,
        currency=entry.legal_entity.base_currency,
        exchange_rate=Decimal("1"),
        source_type="opening_balance",
        source_id=entry.id,
        is_opening=True,
    )
    # System path, not the manual-JV one — a line on a control account
    # (e.g. system_key=OPENING_BALANCE) is posted directly here, same
    # as post_invoice_journal_entry/post_voucher never going through
    # create_manual_journal_entry's allow_manual_posting gate either.
    JournalLine.objects.bulk_create(
        [
            JournalLine(
                entry=journal_entry,
                account=line.account,
                cost_center=line.cost_center,
                party=line.account.party,
                currency=line.currency,
                exchange_rate=line.exchange_rate,
                debit_fc=line.debit_fc,
                credit_fc=line.credit_fc,
                debit=line.debit_base,
                credit=line.credit_base,
            )
            for line in lines
        ]
    )
    return journal_entry


def _maybe_mark_tenant_opening_balances_approved(tenant):
    from apps.organization.models import LegalEntity

    active_entities = LegalEntity.objects.filter(tenant=tenant, is_active=True)
    all_approved = active_entities.exists() and not active_entities.filter(
        opening_approved_at__isnull=True
    ).exists()
    if all_approved and tenant.opening_balances_approved_at is None:
        tenant.opening_balances_approved_at = timezone.now()
        tenant.save(update_fields=["opening_balances_approved_at"])
