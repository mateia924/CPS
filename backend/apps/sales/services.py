import csv
import io
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils.translation import gettext_lazy as _

from apps.inventory.models import ItemBarcode, ItemCategory, UnitOfMeasure
from apps.numbering.services import next_document_number
from apps.parties.models import PartyRole

from .models import Invoice, InvoiceLine, Product

CENTS = Decimal("0.01")
HUNDRED = Decimal("100")


def generate_invoice_number(tenant, legal_entity, issue_date):
    """Next invoice number, e.g. INV-2026-00001 — atomic per (tenant,
    legal_entity, year of issue_date) via apps.numbering (sprint 4.1;
    was COUNT-based and unsafe under concurrent writes, ARCH_REVIEW_1.md
    debt #1)."""
    return next_document_number(tenant, "invoice", legal_entity=legal_entity, date=issue_date)


def recalculate_invoice(invoice):
    """Recompute every line's subtotal/tax/total and the invoice totals
    from quantity * unit_price and tax_rate. This is the only place
    money amounts are computed — always server-side, never client input.
    """
    subtotal = Decimal("0")
    tax_total = Decimal("0")

    lines = list(invoice.lines.select_related(None).all())
    for line in lines:
        line_subtotal = (line.quantity * line.unit_price).quantize(CENTS, rounding=ROUND_HALF_UP)
        line_tax = (line_subtotal * line.tax_rate / HUNDRED).quantize(CENTS, rounding=ROUND_HALF_UP)
        line.line_subtotal = line_subtotal
        line.line_tax = line_tax
        line.line_total = line_subtotal + line_tax
        subtotal += line_subtotal
        tax_total += line_tax

    InvoiceLine.objects.bulk_update(lines, ["line_subtotal", "line_tax", "line_total"])

    invoice.subtotal = subtotal
    invoice.tax_total = tax_total
    invoice.total = subtotal + tax_total
    invoice.base_total = (invoice.total * invoice.exchange_rate).quantize(CENTS, rounding=ROUND_HALF_UP)
    # paid_fc is untouched here (only VoucherAllocation in 5.3 changes
    # it) — recomputing balance_fc/payment_status from it on every
    # totals recalculation keeps them consistent even if a draft's
    # lines are edited (paid_fc is always 0 for a draft anyway, since
    # nothing unissued can be paid against).
    invoice.balance_fc = invoice.total - invoice.paid_fc
    invoice.payment_status = _payment_status_for(invoice.paid_fc, invoice.total)
    invoice.save(
        update_fields=["subtotal", "tax_total", "total", "base_total", "balance_fc", "payment_status"]
    )
    return invoice


def _payment_status_for(paid_fc, total):
    if paid_fc <= 0:
        return Invoice.PaymentStatus.UNPAID
    if paid_fc >= total:
        return Invoice.PaymentStatus.PAID
    return Invoice.PaymentStatus.PARTIAL


def _compute_due_date(party, issue_date):
    """Sprint 5.0: `issue_date + customer.payment_terms_days`, or None
    if the customer role has no payment terms set (PartyRole.details is
    a flat JSON bag — see apps/parties/models.py)."""
    customer_role = party.roles.filter(role=PartyRole.Role.CUSTOMER, is_active=True).first()
    if customer_role is None:
        return None
    days = (customer_role.details or {}).get("payment_terms_days")
    if not days:
        return None
    return issue_date + timedelta(days=int(days))


def _build_lines(invoice, line_inputs):
    """`line_inputs` is a list of {"product": Product, "quantity":
    Decimal, "cost_center": CostCenter | None, "tax_code": TaxCode}.
    Shared by create_invoice and update_invoice so both snapshot
    pricing identically. `tax_rate` is a snapshot of tax_code.rate at
    save time (sprint 4.6, rule 16) — never the product's own tax_rate
    directly, and never free client input."""
    InvoiceLine.objects.bulk_create(
        [
            InvoiceLine(
                invoice=invoice,
                product=item["product"],
                cost_center=item.get("cost_center"),
                tax_code=item["tax_code"],
                description=item["product"].name,
                quantity=item["quantity"],
                unit_price=item["product"].unit_price,
                tax_rate=item["tax_code"].rate,
            )
            for item in line_inputs
        ]
    )


@transaction.atomic
def create_invoice(tenant, party, legal_entity, issue_date, line_inputs, currency, exchange_rate, created_by=None):
    """Create a draft invoice with its lines, snapshot pricing from each
    product, then compute totals. `currency`/`exchange_rate` (sprint
    4.2, 3.11/3.15.3) are already resolved by the caller (auto-pulled
    via apps.treasury.services.get_rate or an explicit override) —
    this function just stores them and lets recalculate_invoice derive
    base_total. `created_by` (sprint 4.5) drives segregation of duties
    on approval — optional so every direct-service-call test/caller
    that predates 4.5 keeps working unchanged."""
    invoice = Invoice.objects.create(
        tenant=tenant,
        party=party,
        legal_entity=legal_entity,
        issue_date=issue_date,
        due_date=_compute_due_date(party, issue_date),
        status=Invoice.Status.DRAFT,
        currency=currency,
        exchange_rate=exchange_rate,
        created_by=created_by,
    )
    _build_lines(invoice, line_inputs)
    return recalculate_invoice(invoice)


@transaction.atomic
def update_invoice(invoice, party, legal_entity, issue_date, line_inputs, currency, exchange_rate):
    """Replace a DRAFT invoice's party/entity/date/lines/currency
    wholesale (same shape as create — the edit form resubmits
    everything, not a partial line patch) and recompute totals. Caller
    must have already checked invoice.status == DRAFT."""
    invoice.party = party
    invoice.legal_entity = legal_entity
    invoice.issue_date = issue_date
    invoice.due_date = _compute_due_date(party, issue_date)
    invoice.currency = currency
    invoice.exchange_rate = exchange_rate
    invoice.save(
        update_fields=["party", "legal_entity", "issue_date", "due_date", "currency", "exchange_rate"]
    )
    invoice.lines.all().delete()
    _build_lines(invoice, line_inputs)
    return recalculate_invoice(invoice)


def _actually_issue(invoice):
    """The real, final step — posts the journal entry and marks the
    invoice ISSUED. Only ever called once a DRAFT invoice is either
    auto-approved or explicitly approved (sprint 4.5); never called
    directly from outside this module."""
    from apps.accounting.services import post_invoice_journal_entry

    invoice.status = Invoice.Status.ISSUED
    update_fields = ["status"]
    if not invoice.number:
        # CFO_REVIEW_1 C6 / decision D2: assigned here, at the first
        # exit from DRAFT — never at create time.
        invoice.number = generate_invoice_number(invoice.tenant, invoice.legal_entity, invoice.issue_date)
        update_fields.append("number")
    invoice.save(update_fields=update_fields)
    post_invoice_journal_entry(invoice)
    return invoice


def credit_limit_check(tenant, party, additional_amount_base):
    """Sprint 6.8 (F8, decision 16): the customer's sub-ledger balance
    (as of today, REPORTABLE_STATUSES basis — same as every other
    balance in this project) plus this invoice's own total, against
    PartyRole.credit_limit. Returns a warning message (str) if that
    would exceed the limit, else None. A customer with no credit_limit
    set is unlimited — never checked at all. Callers decide whether the
    message is just a warning (always, at create) or also a 400 (at
    issue, only in BLOCK mode) — see decision 16's own two call sites."""
    from django.utils import timezone

    from apps.accounting.services import get_or_create_party_role_account, ledger_lines

    customer_role = party.roles.filter(role=PartyRole.Role.CUSTOMER, is_active=True).first()
    if customer_role is None or customer_role.credit_limit is None:
        return None
    account = get_or_create_party_role_account(party, PartyRole.Role.CUSTOMER)
    if account is None:
        return None
    balance = ledger_lines(tenant, account, date_to=timezone.localdate())["closing_balance"]
    projected = balance + additional_amount_base
    if projected <= customer_role.credit_limit:
        return None
    return str(
        _("العميل «%(name)s» يتجاوز حد الائتمان (%(limit)s) — الرصيد المتوقَّع %(projected)s.")
        % {"name": party.name, "limit": customer_role.credit_limit, "projected": projected}
    )


@transaction.atomic
def issue_invoice(invoice, user, request=None):
    """Sprint 4.5 (3.15.1): "الفاتورة بلا قاعدة مطابقة تُعتمد تلقائيًا
    عند الإصدار (سلوك العميل الصغير لا يتغير)" — this single action
    covers the whole DRAFT -> PENDING_APPROVAL -> APPROVED -> ISSUED
    chain transparently for the common case (no rule, or the issuing
    user is already authorized to self-approve): it just becomes
    ISSUED in one call, exactly like before 4.5. Only when a matching
    ApprovalRule blocks the *current* user does this stop short at
    PENDING_APPROVAL — someone else with the required role then calls
    approve_invoice() from "صندوق الاعتماد", which itself finishes the
    issuance (APPROVED -> ISSUED is one step for invoices, no separate
    manual "post" — unlike JournalEntry).
    """
    from apps.approvals.services import can_approve, submit_for_approval

    if invoice.status == Invoice.Status.APPROVED:
        return _actually_issue(invoice)
    if invoice.status != Invoice.Status.DRAFT:
        raise ValidationError(_("Only a draft or approved invoice can be issued."))

    auto_approved = submit_for_approval(invoice, user, "invoice", invoice.base_total, request=request)
    if auto_approved:
        return _actually_issue(invoice)
    if can_approve(invoice, user, "invoice", invoice.base_total):
        from apps.approvals.services import approve as approvals_approve

        approvals_approve(invoice, user, "invoice", invoice.base_total, request=request)
        return _actually_issue(invoice)
    # Genuinely blocked: stays at PENDING_APPROVAL for someone else to
    # approve via the inbox.
    return invoice


@transaction.atomic
def approve_invoice(invoice, user, request=None, emergency_reason=""):
    # CFO_REVIEW_1 C4 — see apps.vouchers.services.approve_voucher's
    # identical comment for why this must wrap _actually_issue too.
    from apps.approvals.services import approve as approvals_approve

    approvals_approve(
        invoice, user, "invoice", invoice.base_total, request=request, emergency_reason=emergency_reason
    )
    return _actually_issue(invoice)


def reject_invoice(invoice, user, reason, request=None):
    from apps.approvals.services import reject as approvals_reject

    approvals_reject(invoice, user, "invoice", reason, request=request)
    return invoice


def withdraw_invoice(invoice, user, request=None):
    """CFO_REVIEW_1 C3."""
    from apps.approvals.services import withdraw as approvals_withdraw

    approvals_withdraw(invoice, user, "invoice", request=request)
    return invoice


class VoidRejected(Exception):
    """Sprint 6.7 (decision 14, C7): both of this function's guards map
    to 409 in the view — a genuinely different document state than the
    plain 400 "not an issued invoice" case."""


def void_invoice(invoice, user, reason="", request=None):
    """Decision 14: (1) a FILED/PAID tax period covering issue_date
    blocks voiding **always**, no override; (2) a delivered invoice
    needs `sales.void_delivered_invoice` (Owner by default) + a
    mandatory reason — both flagged (`is_post_delivery_void`, AuditLog)
    since this is a documented temporary override, not a routine path;
    (3) the reversal itself always posts at today's date regardless of
    the invoice's own (possibly closed) fiscal period — already
    void_invoice_journal_entry's own behavior (CFO_REVIEW_1 C8-style
    exception, decision 3), unchanged here."""
    from apps.access.services import user_has_permission
    from apps.accounting.models import TaxPeriod
    from apps.accounting.services import void_invoice_journal_entry
    from apps.platform.models import AuditLog
    from apps.platform.services import log_action

    if invoice.status != Invoice.Status.ISSUED:
        raise ValidationError(_("Only issued invoices can be voided."))

    tax_period = TaxPeriod.objects.filter(
        tenant=invoice.tenant, legal_entity=invoice.legal_entity,
        start__lte=invoice.issue_date, end__gte=invoice.issue_date,
    ).first()
    if tax_period is not None and tax_period.status in (TaxPeriod.Status.FILED, TaxPeriod.Status.PAID):
        raise VoidRejected(
            str(_("لا يمكن إلغاء هذه الفاتورة — فترة الإقرار الضريبي المحتوية لتاريخها %(status)s.") % {
                "status": tax_period.get_status_display()
            })
        )

    is_post_delivery = invoice.delivered_at is not None
    if is_post_delivery:
        if not user_has_permission(user, "sales.void_delivered_invoice"):
            raise VoidRejected(str(_("لا يمكن إلغاء فاتورة سُلِّمت للعميل بالفعل بدون صلاحية خاصة.")))
        if not reason:
            raise VoidRejected(str(_("إلغاء فاتورة بعد تسليمها يشترط سببًا.")))

    invoice.status = Invoice.Status.CANCELLED
    update_fields = ["status"]
    if is_post_delivery:
        invoice.is_post_delivery_void = True
        update_fields.append("is_post_delivery_void")
    invoice.save(update_fields=update_fields)

    reversal = void_invoice_journal_entry(invoice)

    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER, actor_id=user.id, action="invoice.void",
        target_type="sales.Invoice", target_id=invoice.id, tenant_id=invoice.tenant_id,
        after={
            "number": invoice.number,
            **({"is_post_delivery_void": True, "reason": reason} if is_post_delivery else {}),
        },
        request=request,
    )
    return invoice, reversal


_ITEM_TYPE_LABELS = {
    "مخزني": Product.ItemType.STOCK, "stock": Product.ItemType.STOCK,
    "خدمي": Product.ItemType.SERVICE, "service": Product.ItemType.SERVICE,
    "": Product.ItemType.SERVICE,
}


def import_items_csv(tenant, file_obj):
    """Sprint 7.1 (block 7.1, item 3): CSV columns in this exact order
    — كود، اسم، نوع، فئة، وحدة، باركود، حد إعادة الطلب، تكلفة افتراضية
    (sku, name, item_type, category code, uom code, barcode, reorder
    level, default purchase cost) — first row is a header, skipped.
    `unit_price` isn't one of the spec's columns; a CSV-imported item
    gets 0.00 and is expected to have it set for real afterward (this
    is item SETUP, not a price list import).

    Returns (created_count, errors) where errors is a list of
    {"row": <1-based row number, header excluded>, "error": <Arabic
    message>} — one row's failure never aborts the others; each row
    is its own atomic unit so a later row's success is never undone
    by an earlier row's rollback."""
    decoded = file_obj.read().decode("utf-8-sig")
    reader = csv.reader(io.StringIO(decoded))
    rows = list(reader)
    if rows:
        rows = rows[1:]  # header

    created = 0
    errors = []
    for row_number, row in enumerate(rows, start=1):
        if not row or not any(cell.strip() for cell in row):
            continue
        try:
            with transaction.atomic():
                _import_one_item_row(tenant, row)
            created += 1
        except _ImportRowError as exc:
            errors.append({"row": row_number, "error": str(exc)})
        except (IntegrityError, ValidationError) as exc:
            errors.append({"row": row_number, "error": str(exc)})
    return created, errors


class _ImportRowError(Exception):
    pass


def _import_one_item_row(tenant, row):
    cells = [c.strip() for c in row] + [""] * 8
    sku, name, item_type_raw, category_code, uom_code, barcode, reorder_level_raw, purchase_cost_raw = cells[:8]

    if not sku:
        raise _ImportRowError(str(_("الكود مطلوب.")))
    if not name:
        raise _ImportRowError(str(_("الاسم مطلوب.")))
    if Product.objects.filter(tenant=tenant, sku=sku).exists():
        raise _ImportRowError(str(_("الكود %(sku)s مستخدم من قبل.")) % {"sku": sku})

    item_type = _ITEM_TYPE_LABELS.get(item_type_raw, None)
    if item_type is None:
        raise _ImportRowError(str(_("نوع الصنف غير معروف: %(value)s.")) % {"value": item_type_raw})

    category = None
    if category_code:
        category = ItemCategory.objects.filter(tenant=tenant, code=category_code).first()
        if category is None:
            raise _ImportRowError(str(_("فئة غير موجودة بالكود: %(value)s.")) % {"value": category_code})

    base_uom = None
    if uom_code:
        base_uom = UnitOfMeasure.objects.filter(tenant=tenant, code=uom_code).first()
        if base_uom is None:
            raise _ImportRowError(str(_("وحدة غير موجودة بالكود: %(value)s.")) % {"value": uom_code})

    reorder_level = None
    if reorder_level_raw:
        try:
            reorder_level = Decimal(reorder_level_raw)
        except InvalidOperation:
            raise _ImportRowError(str(_("حد إعادة الطلب ليس رقمًا صحيحًا: %(value)s.")) % {"value": reorder_level_raw})

    purchase_cost_default = None
    if purchase_cost_raw:
        try:
            purchase_cost_default = Decimal(purchase_cost_raw)
        except InvalidOperation:
            raise _ImportRowError(str(_("تكلفة الشراء الافتراضية ليست رقمًا صحيحًا: %(value)s.")) % {"value": purchase_cost_raw})

    if barcode and ItemBarcode.objects.filter(tenant=tenant, barcode=barcode).exists():
        raise _ImportRowError(str(_("الباركود %(value)s مستخدم من قبل.")) % {"value": barcode})

    item = Product.objects.create(
        tenant=tenant, sku=sku, name=name, unit_price=Decimal("0"),
        item_type=item_type, category=category, base_uom=base_uom,
        reorder_level=reorder_level, purchase_cost_default=purchase_cost_default,
    )
    if barcode:
        ItemBarcode.objects.create(tenant=tenant, item=item, barcode=barcode)
