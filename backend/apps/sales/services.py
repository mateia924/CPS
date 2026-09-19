from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction

from .models import Invoice, InvoiceLine

CENTS = Decimal("0.01")
HUNDRED = Decimal("100")


def generate_invoice_number(tenant):
    """Next sequential invoice number for a tenant, e.g. INV-0001.

    TECH DEBT (documented in README "Technical debt"): this counts
    existing invoices and is not safe under concurrent writes for the
    same tenant — a production version needs a DB sequence or
    select-for-update. Acceptable for MVP single-writer usage.
    """
    count = Invoice.objects.filter(tenant=tenant).count()
    return f"INV-{count + 1:04d}"


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
    invoice.save(update_fields=["subtotal", "tax_total", "total"])
    return invoice


def _build_lines(invoice, line_inputs):
    """`line_inputs` is a list of {"product": Product, "quantity":
    Decimal, "cost_center": CostCenter | None}. Shared by create_invoice
    and update_invoice so both snapshot pricing identically."""
    InvoiceLine.objects.bulk_create(
        [
            InvoiceLine(
                invoice=invoice,
                product=item["product"],
                cost_center=item.get("cost_center"),
                description=item["product"].name,
                quantity=item["quantity"],
                unit_price=item["product"].unit_price,
                tax_rate=item["product"].tax_rate,
            )
            for item in line_inputs
        ]
    )


@transaction.atomic
def create_invoice(tenant, party, legal_entity, issue_date, line_inputs):
    """Create a draft invoice with its lines, snapshot pricing from each
    product, then compute totals."""
    invoice = Invoice.objects.create(
        tenant=tenant,
        party=party,
        legal_entity=legal_entity,
        number=generate_invoice_number(tenant),
        issue_date=issue_date,
        status=Invoice.Status.DRAFT,
    )
    _build_lines(invoice, line_inputs)
    return recalculate_invoice(invoice)


@transaction.atomic
def update_invoice(invoice, party, legal_entity, issue_date, line_inputs):
    """Replace a DRAFT invoice's party/entity/date/lines wholesale
    (same shape as create — the edit form resubmits everything, not a
    partial line patch) and recompute totals. Caller must have already
    checked invoice.status == DRAFT."""
    invoice.party = party
    invoice.legal_entity = legal_entity
    invoice.issue_date = issue_date
    invoice.save(update_fields=["party", "legal_entity", "issue_date"])
    invoice.lines.all().delete()
    _build_lines(invoice, line_inputs)
    return recalculate_invoice(invoice)
