from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from apps.numbering.services import next_document_number

from .models import Invoice, InvoiceLine

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
    invoice.save(update_fields=["subtotal", "tax_total", "total", "base_total"])
    return invoice


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
        number=generate_invoice_number(tenant, legal_entity, issue_date),
        issue_date=issue_date,
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
    invoice.currency = currency
    invoice.exchange_rate = exchange_rate
    invoice.save(update_fields=["party", "legal_entity", "issue_date", "currency", "exchange_rate"])
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
    invoice.save(update_fields=["status"])
    post_invoice_journal_entry(invoice)
    return invoice


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


def approve_invoice(invoice, user, request=None):
    from apps.approvals.services import approve as approvals_approve

    approvals_approve(invoice, user, "invoice", invoice.base_total, request=request)
    return _actually_issue(invoice)


def reject_invoice(invoice, user, reason, request=None):
    from apps.approvals.services import reject as approvals_reject

    approvals_reject(invoice, user, "invoice", reason, request=request)
    return invoice
