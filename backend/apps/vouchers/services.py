from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounting.models import JournalEntry, TaxCode
from apps.accounting.services import (
    build_journal_lines_with_fx_rounding,
    get_or_create_party_role_account,
    get_or_create_treasury_account,
    get_system_account,
)
from apps.numbering.services import next_document_number
from apps.platform.models import AuditLog
from apps.platform.services import log_action
from apps.treasury.services import ExchangeRateNotFound, get_rate, treasury_balance

from .models import Voucher, VoucherAllocation, VoucherLine

CENTS = Decimal("0.01")
HUNDRED = Decimal("100")

TREASURY_SYSTEM_KEY = {"bank": "BANKS", "cash_box": "CASH", "custody": "CUSTODIES"}


class VoucherValidationError(ValidationError):
    pass


def _treasury_instance(tenant, kind, treasury_id):
    from apps.treasury.models import Bank, CashBox, Custody

    model = {"bank": Bank, "cash_box": CashBox, "custody": Custody}.get(kind)
    if model is None:
        raise VoucherValidationError({"treasury_kind": [_("Unknown treasury kind.")]})
    try:
        return model.objects.get(tenant=tenant, id=treasury_id)
    except model.DoesNotExist:
        raise VoucherValidationError({"treasury_id": [_("Treasury account not found.")]})


def _treasury_account(instance, kind):
    account = get_or_create_treasury_account(instance, TREASURY_SYSTEM_KEY[kind])
    if account is None:
        raise VoucherValidationError(
            {"treasury_kind": [_("No system account found for this treasury kind — check the chart of accounts.")]}
        )
    return account


@transaction.atomic
def create_voucher(
    tenant, user, voucher_type, legal_entity, date, treasury_kind, treasury_id, line_specs,
    settlement_kind=None, party=None, party_role="", payee_name="", payment_method=Voucher.PaymentMethod.CASH,
    reference="", description="", exchange_rate_override=None,
):
    """Builds a DRAFT voucher + lines. No number yet (decision 9 — see
    services.assign_number_and_post below), no journal entry yet
    (draft never posts). `line_specs` is a list of dicts already
    resolved against the tenant (account/invoice objects, not raw ids)
    — see views.py for the raw-input -> resolved-object step, same
    split as every other create-flow in this project.
    """
    treasury_instance = _treasury_instance(tenant, treasury_kind, treasury_id)
    if treasury_instance.legal_entity_id != legal_entity.id:
        raise VoucherValidationError(
            {"legal_entity": [_("The treasury account belongs to a different legal entity.")]}
        )
    currency = treasury_instance.currency
    base_currency = legal_entity.base_currency
    overridden = False
    if currency == base_currency:
        exchange_rate = Decimal("1")
    elif exchange_rate_override is not None:
        exchange_rate = exchange_rate_override
        overridden = True
    else:
        try:
            exchange_rate = get_rate(tenant, currency, base_currency, date)
        except ExchangeRateNotFound as exc:
            raise VoucherValidationError({"exchange_rate": [str(exc.message)]})

    for spec in line_specs:
        if spec["line_type"] == VoucherLine.LineType.INVOICE:
            invoice = spec["invoice"]
            if invoice.legal_entity_id != legal_entity.id:
                raise VoucherValidationError({"lines": [_("Invoice belongs to a different legal entity.")]})
            if invoice.party_id != (party.id if party else None):
                raise VoucherValidationError({"lines": [_("Invoice does not belong to this voucher's party.")]})
            allocated = spec.get("allocated_invoice_fc", spec["amount_fc"])
            if allocated > invoice.balance_fc:
                raise VoucherValidationError(
                    {"lines": [_("Allocated amount exceeds the invoice's remaining balance.")]}
                )

    voucher = Voucher.objects.create(
        tenant=tenant,
        legal_entity=legal_entity,
        voucher_type=voucher_type,
        settlement_kind=settlement_kind,
        date=date,
        currency=currency,
        exchange_rate=exchange_rate,
        exchange_rate_overridden=overridden,
        treasury_kind=treasury_kind,
        party=party,
        party_role=party_role or None,
        payee_name=payee_name,
        payment_method=payment_method,
        reference=reference,
        description=description,
        created_by=user,
        **{treasury_kind: treasury_instance},
    )

    total_fc = Decimal("0")
    lines = []
    for i, spec in enumerate(line_specs, start=1):
        amount_fc = spec["amount_fc"]
        total_fc += _line_cash_amount(spec)
        line = VoucherLine(
            voucher=voucher,
            line_no=i,
            line_type=spec["line_type"],
            invoice=spec.get("invoice"),
            allocated_invoice_fc=spec.get("allocated_invoice_fc"),
            account=spec.get("account"),
            tax_code=spec.get("tax_code"),
            amount_includes_tax=spec.get("amount_includes_tax", False),
            cost_center=spec.get("cost_center"),
            description=spec.get("description", ""),
            amount_fc=amount_fc,
        )
        lines.append(line)
    VoucherLine.objects.bulk_create(lines)

    voucher.total_fc = total_fc
    voucher.total_base = (total_fc * exchange_rate).quantize(CENTS, rounding=ROUND_HALF_UP)
    voucher.save(update_fields=["total_fc", "total_base"])

    if overridden:
        log_action(
            actor_type=AuditLog.ActorType.TENANT_USER, actor_id=user.id,
            action="voucher.exchange_rate_overridden", target_type="voucher", target_id=voucher.id,
            tenant_id=tenant.id, after={"currency": currency, "exchange_rate": str(exchange_rate)},
        )
    return voucher


def _account_line_tax_split(amount_fc, tax_code, amount_includes_tax):
    """gross/net/tax for one ACCOUNT-type line — ROUND_HALF_UP to the
    cent, tax = gross - net (never computed the other way, so the two
    always sum back to gross exactly)."""
    rate = tax_code.rate if tax_code else Decimal("0")
    if amount_includes_tax:
        gross = amount_fc
        net = (gross / (1 + rate / HUNDRED)).quantize(CENTS, rounding=ROUND_HALF_UP)
        tax = gross - net
    else:
        net = amount_fc
        tax = (net * rate / HUNDRED).quantize(CENTS, rounding=ROUND_HALF_UP)
        gross = net + tax
    return net, tax, gross


def _line_cash_amount(spec):
    """The actual treasury-side (cash) impact of one line spec, used to
    compute Voucher.total_fc at create time — must exactly match what
    _build_posting_specs later posts against the treasury account, or
    the entry won't balance. INVOICE/ON_ACCOUNT lines are untouched
    (amount_fc already IS the cash amount there). An ACCOUNT line's
    amount_fc is only ever the cash amount too when there's no tax
    split to apply: with a deductible tax_code (a separate tax line
    gets added) or a NONE-deductible one (folded into the main line),
    the true cash impact is always the gross (net+tax) regardless of
    amount_includes_tax; REVERSE_CHARGE is the one exception — its two
    self-assessed lines net to zero and never touch the treasury line,
    so only the net amount leaves the cash box/bank."""
    if spec["line_type"] != VoucherLine.LineType.ACCOUNT:
        return spec["amount_fc"]
    tax_code = spec.get("tax_code")
    if not tax_code:
        return spec["amount_fc"]
    net, _tax, gross = _account_line_tax_split(spec["amount_fc"], tax_code, spec.get("amount_includes_tax", False))
    if tax_code.kind == TaxCode.Kind.REVERSE_CHARGE:
        return net
    return gross


def _voucher_tax_account(tenant, tax_code, is_receipt):
    """Sprint 5.3: unlike invoice lines (resolve_tax_posting_account,
    driven by tax_code.direction — a code IS inherently output or
    input there), a voucher's direction is driven by the VOUCHER
    (receipt = output tax on other income, payment = input tax on an
    expense), regardless of what the code's own `direction` says (a
    "both"-direction code like the seeded standard rate is meant to be
    reusable on either side). NONE-deductible returns None — its tax
    amount gets folded into the expense line itself instead."""
    if tax_code.deductible == TaxCode.Deductible.NONE:
        return None
    # Deliberately ignores tax_code.account (unlike
    # resolve_tax_posting_account) — every compliance-package code gets
    # that field auto-populated from its sales-side system_key at seed
    # time (e.g. "S" -> VAT_OUTPUT), which would otherwise always win
    # here and defeat the whole point of this function: a payment using
    # code "S" must land on VAT_INPUT, not VAT_OUTPUT, even though the
    # code's own account/direction says output.
    return get_system_account(tenant, "VAT_OUTPUT" if is_receipt else "VAT_INPUT")


def _build_posting_specs(tenant, voucher):
    """Returns (line_specs for build_journal_lines_with_fx_rounding,
    allocation_specs to create as VoucherAllocation rows after the
    entry is built)."""
    is_receipt = voucher.voucher_type == Voucher.VoucherType.RECEIPT
    base_currency = voucher.legal_entity.base_currency
    specs = []
    allocation_specs = []
    fx_diff_total = Decimal("0")

    for line in voucher.lines.all():
        if line.line_type == VoucherLine.LineType.INVOICE:
            invoice = line.invoice
            account = get_or_create_party_role_account(voucher.party, voucher.party_role)
            if account is None:
                raise VoucherValidationError(
                    {"lines": [_("Could not resolve the party's sub-ledger account.")]}
                )
            base_settled = (line.amount_fc * voucher.exchange_rate).quantize(CENTS, rounding=ROUND_HALF_UP)
            base_at_invoice_rate = (line.allocated_invoice_fc * invoice.exchange_rate).quantize(
                CENTS, rounding=ROUND_HALF_UP
            )
            fx_difference = base_settled - base_at_invoice_rate
            fx_diff_total += fx_difference
            specs.append(
                {
                    "account": account, "cost_center": None, "description": line.description,
                    "currency": invoice.currency, "exchange_rate": invoice.exchange_rate,
                    "debit_fc": Decimal("0") if is_receipt else line.allocated_invoice_fc,
                    "credit_fc": line.allocated_invoice_fc if is_receipt else Decimal("0"),
                    "debit_base": Decimal("0") if is_receipt else base_at_invoice_rate,
                    "credit_base": base_at_invoice_rate if is_receipt else Decimal("0"),
                }
            )
            allocation_specs.append(
                {
                    "voucher_line": line, "invoice": invoice,
                    "allocated_invoice_fc": line.allocated_invoice_fc,
                    "base_at_invoice_rate": base_at_invoice_rate, "base_settled": base_settled,
                    "fx_difference_base": fx_difference,
                }
            )

        elif line.line_type == VoucherLine.LineType.ON_ACCOUNT:
            account = get_or_create_party_role_account(voucher.party, voucher.party_role)
            if account is None:
                raise VoucherValidationError(
                    {"lines": [_("Could not resolve the party's sub-ledger account.")]}
                )
            base = (line.amount_fc * voucher.exchange_rate).quantize(CENTS, rounding=ROUND_HALF_UP)
            specs.append(
                {
                    "account": account, "cost_center": line.cost_center, "description": line.description,
                    "currency": voucher.currency, "exchange_rate": voucher.exchange_rate,
                    "debit_fc": Decimal("0") if is_receipt else line.amount_fc,
                    "credit_fc": line.amount_fc if is_receipt else Decimal("0"),
                    "debit_base": Decimal("0") if is_receipt else base,
                    "credit_base": base if is_receipt else Decimal("0"),
                }
            )

        elif line.line_type == VoucherLine.LineType.ACCOUNT:
            net, tax, _gross = _account_line_tax_split(line.amount_fc, line.tax_code, line.amount_includes_tax)
            tax_account = _voucher_tax_account(tenant, line.tax_code, is_receipt) if line.tax_code and tax != 0 else None
            main_amount_fc = net if tax_account is not None or not line.tax_code else net + tax
            main_base = (main_amount_fc * voucher.exchange_rate).quantize(CENTS, rounding=ROUND_HALF_UP)
            specs.append(
                {
                    "account": line.account, "cost_center": line.cost_center, "description": line.description,
                    "currency": voucher.currency, "exchange_rate": voucher.exchange_rate,
                    "debit_fc": Decimal("0") if is_receipt else main_amount_fc,
                    "credit_fc": main_amount_fc if is_receipt else Decimal("0"),
                    "debit_base": Decimal("0") if is_receipt else main_base,
                    "credit_base": main_base if is_receipt else Decimal("0"),
                }
            )
            if line.tax_code and tax != 0:
                if line.tax_code.kind == TaxCode.Kind.REVERSE_CHARGE:
                    tax_base = (tax * voucher.exchange_rate).quantize(CENTS, rounding=ROUND_HALF_UP)
                    output_account = get_system_account(tenant, "VAT_OUTPUT")
                    input_account = get_system_account(tenant, "VAT_INPUT")
                    specs.append(
                        {
                            "account": output_account, "cost_center": line.cost_center,
                            "currency": base_currency, "exchange_rate": Decimal("1"),
                            "debit_fc": Decimal("0"), "credit_fc": tax_base,
                            "debit_base": Decimal("0"), "credit_base": tax_base,
                        }
                    )
                    specs.append(
                        {
                            "account": input_account, "cost_center": line.cost_center,
                            "currency": base_currency, "exchange_rate": Decimal("1"),
                            "debit_fc": tax_base, "credit_fc": Decimal("0"),
                            "debit_base": tax_base, "credit_base": Decimal("0"),
                        }
                    )
                elif tax_account is not None:
                    tax_base = (tax * voucher.exchange_rate).quantize(CENTS, rounding=ROUND_HALF_UP)
                    specs.append(
                        {
                            "account": tax_account, "cost_center": line.cost_center,
                            "currency": voucher.currency, "exchange_rate": voucher.exchange_rate,
                            "debit_fc": tax if not is_receipt else Decimal("0"),
                            "credit_fc": tax if is_receipt else Decimal("0"),
                            "debit_base": tax_base if not is_receipt else Decimal("0"),
                            "credit_base": tax_base if is_receipt else Decimal("0"),
                        }
                    )
                # tax_account is None and kind != REVERSE_CHARGE: NONE-deductible,
                # already folded into main_amount_fc above — nothing more to post.

    # One aggregate FX_REALIZED line (only ever nonzero for RECEIPT +
    # INVOICE lines, since ON_ACCOUNT/ACCOUNT always use the voucher's
    # own rate consistently with the treasury line — no drift to book).
    if fx_diff_total != 0:
        fx_account = get_system_account(tenant, "FX_REALIZED")
        if fx_diff_total > 0:
            specs.append(
                {
                    "account": fx_account, "currency": base_currency, "exchange_rate": Decimal("1"),
                    "debit_fc": Decimal("0"), "credit_fc": fx_diff_total,
                    "debit_base": Decimal("0"), "credit_base": fx_diff_total,
                }
            )
        else:
            specs.append(
                {
                    "account": fx_account, "currency": base_currency, "exchange_rate": Decimal("1"),
                    "debit_fc": -fx_diff_total, "credit_fc": Decimal("0"),
                    "debit_base": -fx_diff_total, "credit_base": Decimal("0"),
                }
            )

    # The treasury line itself, last, sized to whatever balances the rest.
    treasury_instance = getattr(voucher, voucher.treasury_kind)
    treasury_account = _treasury_account(treasury_instance, voucher.treasury_kind)
    specs.append(
        {
            "account": treasury_account, "currency": voucher.currency, "exchange_rate": voucher.exchange_rate,
            "debit_fc": voucher.total_fc if is_receipt else Decimal("0"),
            "credit_fc": Decimal("0") if is_receipt else voucher.total_fc,
            "debit_base": voucher.total_base if is_receipt else Decimal("0"),
            "credit_base": Decimal("0") if is_receipt else voucher.total_base,
        }
    )
    return specs, allocation_specs


def _balance_warnings_and_checks(tenant, voucher):
    """Returns a list of warning strings; raises VoucherValidationError
    (400) for the hard-block cases (decision list, block 5.3)."""
    warnings = []
    is_payment_out = voucher.voucher_type == Voucher.VoucherType.PAYMENT
    treasury_instance = getattr(voucher, voucher.treasury_kind)
    current = treasury_balance(tenant, voucher.treasury_kind, treasury_instance.id)["fc"]

    if is_payment_out:
        projected = current - voucher.total_fc
        if voucher.treasury_kind in ("cash_box", "custody") and projected < 0:
            raise VoucherValidationError(
                {"detail": [_("Insufficient balance in this treasury account for this voucher.")]}
            )
        if voucher.treasury_kind == "bank" and projected < 0:
            warnings.append(str(_("This will make the bank account balance negative.")))
    else:
        projected = current + voucher.total_fc
        if voucher.treasury_kind == "cash_box" and treasury_instance.max_balance is not None:
            if projected > treasury_instance.max_balance:
                warnings.append(str(_("This will exceed the cash box's configured maximum balance.")))

    return warnings


def _implicit_rate_warnings(voucher):
    warnings = []
    for line in voucher.lines.filter(line_type=VoucherLine.LineType.INVOICE):
        if not line.allocated_invoice_fc:
            continue
        implicit_rate = (line.amount_fc * voucher.exchange_rate) / line.allocated_invoice_fc
        try:
            market_rate = get_rate(
                voucher.tenant, voucher.currency, voucher.legal_entity.base_currency, voucher.date
            )
        except Exception:
            continue
        if market_rate and abs(implicit_rate - market_rate) / market_rate > Decimal("0.10"):
            warnings.append(str(_("The implicit rate on this allocation is more than 10% off the recorded exchange rate — please verify the amount.")))
    return warnings


@transaction.atomic
def post_voucher(voucher, user, request=None):
    """POST /vouchers/{id}/post/ — decision list: "إرسال + (اعتماد
    تلقائي إن لم تنطبق قاعدة) + ترحيل في طلب واحد؛ إن انطبقت قاعدة →
    202 وPENDING_APPROVAL". Returns (voucher, warnings)."""
    from apps.approvals.services import submit_for_approval

    if voucher.status != Voucher.Status.DRAFT:
        raise VoucherValidationError({"detail": [_("Only a draft voucher can be submitted.")]})

    warnings = _balance_warnings_and_checks(voucher.tenant, voucher) + _implicit_rate_warnings(voucher)

    doc_type = f"voucher_{voucher.voucher_type}"
    auto_approved = submit_for_approval(voucher, user, doc_type, voucher.total_base, request=request)
    if not auto_approved:
        return voucher, warnings

    _actually_post(voucher, user, request=request)
    return voucher, warnings


def _actually_post(voucher, user, request=None):
    from django.contrib.contenttypes.models import ContentType

    specs, allocation_specs = _build_posting_specs(voucher.tenant, voucher)
    entry = JournalEntry.objects.create(
        tenant=voucher.tenant,
        legal_entity=voucher.legal_entity,
        date=voucher.date,
        memo=voucher.description or f"{voucher.get_voucher_type_display()} {voucher.number or ''}".strip(),
        reference=voucher.reference,
        number=next_document_number(voucher.tenant, "journal_entry", voucher.legal_entity, voucher.date),
        status=JournalEntry.Status.POSTED,
        # source_type kept as the plain-text marker every existing
        # check reads (e.g. JournalEntryViewSet.reverse() refusing to
        # reverse a system-generated entry directly); content_type/
        # object_id is the real GenericFK alongside it, same dual
        # pattern already used for invoices (4.4).
        source_type=f"voucher_{voucher.voucher_type}",
        source_id=voucher.id,
        content_type=ContentType.objects.get_for_model(Voucher),
        object_id=voucher.id,
        currency=voucher.currency,
        exchange_rate=voucher.exchange_rate,
    )
    lines = build_journal_lines_with_fx_rounding(voucher.tenant, entry, specs, voucher.exchange_rate)
    from apps.accounting.models import JournalLine

    JournalLine.objects.bulk_create(lines)

    if not voucher.number:
        voucher.number = next_document_number(
            voucher.tenant, f"voucher_{voucher.voucher_type}", voucher.legal_entity, voucher.date
        )
    voucher.status = Voucher.Status.POSTED
    voucher.journal_entry = entry
    voucher.posted_at = timezone.now()
    voucher.save(update_fields=["number", "status", "journal_entry", "posted_at"])

    for alloc_spec in allocation_specs:
        VoucherAllocation.objects.create(tenant=voucher.tenant, **alloc_spec)
    if allocation_specs:
        _recompute_invoice_payment_fields([a["invoice"] for a in allocation_specs])

    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER, actor_id=user.id if user else None,
        action="voucher.posted", target_type="voucher", target_id=voucher.id,
        tenant_id=voucher.tenant_id, after={"journal_entry_id": str(entry.id), "number": voucher.number},
        request=request,
    )
    return voucher


def _recompute_invoice_payment_fields(invoices):
    from apps.sales.models import Invoice
    from apps.sales.services import _payment_status_for

    for invoice in {inv.id: inv for inv in invoices}.values():
        invoice.refresh_from_db()
        paid_fc = sum(
            (a.allocated_invoice_fc for a in invoice.allocations.filter(is_reversed=False)), Decimal("0")
        )
        invoice.paid_fc = paid_fc
        invoice.balance_fc = invoice.total - paid_fc
        invoice.payment_status = _payment_status_for(paid_fc, invoice.total)
        invoice.save(update_fields=["paid_fc", "balance_fc", "payment_status"])
    # PAID sets Invoice.status too when the balance is fully cleared
    # (docs/SYSTEM_ANALYSIS.md Status.PAID, seeded since sprint 1 but
    # never actually reached before this sprint had a payment engine).
    for invoice in {inv.id: inv for inv in invoices}.values():
        if invoice.balance_fc <= Decimal("0.005") and invoice.status == Invoice.Status.ISSUED:
            invoice.status = Invoice.Status.PAID
            invoice.save(update_fields=["status"])


def approve_voucher(voucher, user, request=None):
    from apps.approvals.services import approve as approvals_approve

    approvals_approve(voucher, user, f"voucher_{voucher.voucher_type}", voucher.total_base, request=request)
    _actually_post(voucher, user, request=request)
    return voucher


def reject_voucher(voucher, user, reason, request=None):
    from apps.approvals.services import reject as approvals_reject

    approvals_reject(voucher, user, f"voucher_{voucher.voucher_type}", reason, request=request)
    return voucher


def withdraw_voucher(voucher, user, request=None):
    if voucher.status != Voucher.Status.PENDING_APPROVAL:
        raise VoucherValidationError({"detail": [_("Only a pending-approval voucher can be withdrawn.")]})
    if voucher.created_by_id != user.id:
        raise VoucherValidationError({"detail": [_("Only the creator can withdraw this voucher.")]})
    voucher.status = Voucher.Status.DRAFT
    voucher.save(update_fields=["status"])
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER, actor_id=user.id, action="voucher.withdrawn",
        target_type="voucher", target_id=voucher.id, tenant_id=voucher.tenant_id, request=request,
    )
    return voucher


@transaction.atomic
def reverse_voucher(voucher, user, reason, request=None):
    from apps.accounting.services import reverse_journal_entry

    if voucher.status != Voucher.Status.POSTED:
        raise VoucherValidationError({"detail": [_("Only a posted voucher can be reversed.")]})
    if not reason:
        raise VoucherValidationError({"detail": [_("A reason is required to reverse a voucher.")]})

    reverse_journal_entry(voucher.journal_entry, user, reason)

    affected_invoices = []
    for allocation in VoucherAllocation.objects.filter(voucher_line__voucher=voucher, is_reversed=False):
        allocation.is_reversed = True
        allocation.save(update_fields=["is_reversed"])
        affected_invoices.append(allocation.invoice)
    if affected_invoices:
        from apps.sales.models import Invoice

        for invoice in affected_invoices:
            invoice.refresh_from_db()
            if invoice.status == Invoice.Status.PAID:
                invoice.status = Invoice.Status.ISSUED
                invoice.save(update_fields=["status"])
        _recompute_invoice_payment_fields(affected_invoices)

    voucher.status = Voucher.Status.REVERSED
    voucher.save(update_fields=["status"])
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER, actor_id=user.id, action="voucher.reversed",
        target_type="voucher", target_id=voucher.id, tenant_id=voucher.tenant_id,
        after={"reason": reason}, request=request,
    )
    return voucher
