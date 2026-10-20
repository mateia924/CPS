"""Sprint 8.2 (D7): paying supplier bills.

- Payment vouchers settle bills through BILL lines (apps.vouchers.services:
  validation at creation, re-checked under the bill's row lock at posting,
  FX difference at the bill's rate vs the voucher's).
- An advance (a posted payment-voucher ADVANCE or ON_ACCOUNT line to the
  supplier) is applied to a bill here: apply_advance / withdraw_application.
- «دفع نقدي الآن»: pay_now builds a payment voucher fully allocated to the
  bill and posts it through the ordinary voucher path (approval included).
"""

from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.platform.models import AuditLog
from apps.platform.services import log_action

from .bills import bill_balance
from .models import AdvanceApplication, SupplierBill

CENTS = Decimal("0.01")


def _q(value):
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def advance_remaining(line):
    from django.db.models import Sum

    applied = line.advance_applications.filter(is_reversed=False).aggregate(s=Sum("amount_fc"))["s"] or Decimal("0")
    return line.amount_fc - applied


def open_advances(bill):
    """Posted advance lines of this bill's supplier, entity and currency
    with something left to apply — what the bill screen offers."""
    from apps.vouchers.models import Voucher, VoucherLine

    lines = VoucherLine.objects.filter(
        voucher__tenant=bill.tenant, voucher__status=Voucher.Status.POSTED,
        voucher__voucher_type=Voucher.VoucherType.PAYMENT, voucher__party=bill.supplier,
        voucher__party_role=Voucher.PartyRoleChoice.SUPPLIER, voucher__legal_entity=bill.legal_entity,
        voucher__currency=bill.currency,
        line_type__in=[VoucherLine.LineType.ADVANCE, VoucherLine.LineType.ON_ACCOUNT],
    ).select_related("voucher").order_by("voucher__date", "voucher__number")
    return [(line, advance_remaining(line)) for line in lines if advance_remaining(line) > 0]


def _validate_source(bill, line):
    from apps.vouchers.models import Voucher, VoucherLine

    voucher = line.voucher
    if line.line_type not in (VoucherLine.LineType.ADVANCE, VoucherLine.LineType.ON_ACCOUNT):
        raise ValidationError("المصدر ليس دفعة مقدمة ولا دفعة على الحساب.")
    if voucher.status != Voucher.Status.POSTED or voucher.voucher_type != Voucher.VoucherType.PAYMENT:
        raise ValidationError("الدفعة المقدمة يجب أن تكون سند صرف مرحَّلًا.")
    if voucher.party_id != bill.supplier_id or voucher.party_role != Voucher.PartyRoleChoice.SUPPLIER:
        raise ValidationError("الدفعة المقدمة لمورد آخر.")
    if voucher.legal_entity_id != bill.legal_entity_id:
        raise ValidationError("الدفعة المقدمة في كيان آخر.")
    if voucher.currency != bill.currency:
        raise ValidationError(f"عملة الدفعة المقدمة ({voucher.currency}) غير عملة الفاتورة ({bill.currency}).")


@transaction.atomic
def apply_advance(bill, line, amount, user, request=None, on_date=None):
    from django.contrib.contenttypes.models import ContentType

    from apps.accounting.models import JournalEntry, JournalLine
    from apps.accounting.periods import assert_open_period
    from apps.accounting.services import (
        build_journal_lines_with_fx_rounding,
        get_or_create_party_role_account,
        get_required_system_account,
    )
    from apps.numbering.services import next_document_number
    from apps.parties.models import PartyRole
    from apps.vouchers.models import Voucher, VoucherLine

    bill = SupplierBill.objects.select_for_update().get(pk=bill.pk)
    Voucher.objects.select_for_update().get(pk=line.voucher_id)
    line = VoucherLine.objects.select_related("voucher").get(pk=line.pk)
    if bill.status != SupplierBill.Status.POSTED:
        raise ValidationError("لا تُخصَّص دفعة مقدمة إلا على فاتورة مرحَّلة.")
    _validate_source(bill, line)
    if amount is None or amount <= 0:
        raise ValidationError({"amount": ["المبلغ يجب أن يكون أكبر من صفر."]})
    open_bill, open_advance = bill_balance(bill), advance_remaining(line)
    if amount > open_bill:
        raise ValidationError({"amount": [f"المبلغ أكبر من المتبقي على الفاتورة ({open_bill})."]})
    if amount > open_advance:
        raise ValidationError({"amount": [f"المبلغ أكبر من المتبقي من الدفعة المقدمة ({open_advance})."]})

    voucher = line.voucher
    on_date = on_date or max(timezone.localdate(), bill.date, voucher.date)
    assert_open_period(bill.tenant, on_date)
    base_bill = _q(amount * bill.exchange_rate)
    base_advance = _q(amount * voucher.exchange_rate)
    # More base paid (advance rate) than the bill booked = a loss.
    fx = base_advance - base_bill
    application = AdvanceApplication.objects.create(
        tenant=bill.tenant, source_line=line, supplier_bill=bill, date=on_date, amount_fc=amount,
        base_at_bill_rate=base_bill, base_at_advance_rate=base_advance, fx_difference_base=fx, created_by=user,
    )

    supplier_account = get_or_create_party_role_account(bill.supplier, PartyRole.Role.SUPPLIER)
    fx_account = get_required_system_account(bill.tenant, "FX_REALIZED")
    zero = Decimal("0")
    specs = []
    if line.line_type == VoucherLine.LineType.ADVANCE:
        specs.append({
            "account": supplier_account, "currency": bill.currency, "exchange_rate": bill.exchange_rate,
            "debit_fc": amount, "credit_fc": zero, "debit_base": base_bill, "credit_base": zero,
            "description": f"{bill.number} ← {voucher.number}",
        })
        specs.append({
            "account": get_required_system_account(bill.tenant, "SUPPLIER_ADVANCES"), "currency": voucher.currency,
            "exchange_rate": voucher.exchange_rate, "debit_fc": zero, "credit_fc": amount,
            "debit_base": zero, "credit_base": base_advance, "description": f"{bill.number} ← {voucher.number}",
        })
    elif fx:
        # ON_ACCOUNT: the debit is already on the supplier's account at the
        # advance's rate; only the base difference to the bill's rate moves.
        specs.append({
            "account": supplier_account, "currency": bill.currency, "exchange_rate": bill.exchange_rate,
            "debit_fc": zero, "credit_fc": zero,
            "debit_base": zero if fx > 0 else -fx, "credit_base": fx if fx > 0 else zero,
            "description": f"{bill.number} ← {voucher.number}",
        })
    if specs and fx:
        specs.append({
            "account": fx_account, "currency": bill.legal_entity.base_currency, "exchange_rate": Decimal("1"),
            "debit_fc": fx if fx > 0 else zero, "credit_fc": zero if fx > 0 else -fx,
            "debit_base": fx if fx > 0 else zero, "credit_base": zero if fx > 0 else -fx,
        })
    if specs:
        entry = JournalEntry.objects.create(
            tenant=bill.tenant, legal_entity=bill.legal_entity, date=on_date,
            memo=f"تخصيص دفعة مقدمة {voucher.number} على فاتورة المورد {bill.number}", reference=bill.bill_number,
            number=next_document_number(bill.tenant, "journal_entry", bill.legal_entity, on_date),
            status=JournalEntry.Status.POSTED, produced_by=JournalEntry.ProducedBy.ADVANCE_APPLICATION,
            content_type=ContentType.objects.get_for_model(AdvanceApplication), object_id=application.id,
            currency=bill.currency, exchange_rate=bill.exchange_rate, created_by=user,
        )
        JournalLine.objects.bulk_create(build_journal_lines_with_fx_rounding(bill.tenant, entry, specs, bill.exchange_rate))
        application.journal_entry = entry
        application.save(update_fields=["journal_entry"])
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER, actor_id=user.id, action="supplier_bill.advance_applied",
        target_type="supplier_bill", target_id=bill.id, tenant_id=bill.tenant_id,
        after={"voucher": voucher.number, "amount": str(amount)}, request=request,
    )
    return application


@transaction.atomic
def withdraw_application(application, user, reason, request=None):
    from apps.accounting.services import reverse_journal_entry

    application = AdvanceApplication.objects.select_for_update().get(pk=application.pk)
    if application.is_reversed:
        raise ValidationError("هذا التخصيص مُلغى من قبل.")
    if not (reason or "").strip():
        raise ValidationError("سبب الإلغاء مطلوب.")
    if application.journal_entry_id:
        reverse_journal_entry(application.journal_entry, user, reason)
    application.is_reversed = True
    application.save(update_fields=["is_reversed"])
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER, actor_id=user.id, action="supplier_bill.advance_withdrawn",
        target_type="supplier_bill", target_id=application.supplier_bill_id, tenant_id=application.tenant_id,
        after={"amount": str(application.amount_fc), "reason": reason}, request=request,
    )
    return application


def pay_now(bill, user, treasury_kind, treasury_id, payment_method, request=None, on_date=None):
    """«دفع نقدي الآن» (D4, shipped in 8.2): a payment voucher for the bill's
    whole open balance, one BILL line, posted through the ordinary voucher
    path — so the voucher approval rule, the treasury balance check and the
    bill lock at posting all apply. Same currency only: the treasury account
    must be in the bill's currency. Returns (voucher, warnings); the voucher
    may be PENDING_APPROVAL if a rule holds it."""
    from apps.vouchers.models import Voucher, VoucherLine
    from apps.vouchers.services import _treasury_instance, create_voucher, post_voucher

    if bill.status != SupplierBill.Status.POSTED:
        raise ValidationError("لا يُدفع إلا لفاتورة مرحَّلة.")
    balance = bill_balance(bill)
    if balance <= 0:
        raise ValidationError("الفاتورة مسدَّدة بالكامل.")
    treasury = _treasury_instance(bill.tenant, treasury_kind, treasury_id)
    if treasury.currency != bill.currency:
        raise ValidationError(
            {"treasury_id": [f"عملة حساب الخزينة ({treasury.currency}) غير عملة الفاتورة ({bill.currency}) — استخدم سند الصرف للدفع بعملة أخرى."]}
        )
    with transaction.atomic():
        voucher = create_voucher(
            bill.tenant, user, Voucher.VoucherType.PAYMENT, bill.legal_entity, on_date or timezone.localdate(),
            treasury_kind, treasury_id,
            [{"line_type": VoucherLine.LineType.BILL, "supplier_bill": bill, "amount_fc": balance,
              "allocated_invoice_fc": balance, "description": bill.bill_number}],
            party=bill.supplier, party_role=Voucher.PartyRoleChoice.SUPPLIER, payment_method=payment_method,
            reference=bill.bill_number, description=f"سداد فاتورة المورد {bill.number}",
        )
        voucher, warnings = post_voucher(voucher, user, request=request)
    return voucher, warnings
