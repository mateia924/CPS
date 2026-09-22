import json
from collections import OrderedDict
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.numbering.services import next_document_number
from apps.platform.models import AuditLog
from apps.platform.services import log_action

from .models import Account, JournalEntry, JournalLine

# Sprint 4.4 (3.15.1): POSTED and REVERSED entries both contribute to
# every balance/report — see DocumentStateMixin's docstring for why
# REVERSED isn't an exclusion. DRAFT/PENDING_APPROVAL/APPROVED never do
# (rule 13: "لا قيد محاسبي يُرحَّل إلا من مستند بحالة POSTED").
REPORTABLE_STATUSES = [JournalEntry.Status.POSTED, JournalEntry.Status.REVERSED]

CHART_TEMPLATES_DIR = Path(__file__).resolve().parent / "chart_templates"

# Fallback codes for a chart that predates sprint 4.3 (system_key didn't
# exist) or otherwise lacks a system_key for something get_system_account
# needs — see get_system_account's docstring. Not used when the tenant's
# chart already has the matching system_key (the normal case for every
# tenant registered from 4.3 onward).
_LEGACY_FALLBACK_CODES = {
    "SALES": "4000",
}

CENTS = Decimal("0.01")
FX_ROUNDING_TOLERANCE = Decimal("0.05")

# Sprint 3.3/3.4: which system_key parent a given PartyRole.Role's
# sub-ledger account is created under. Deliberately excludes BANK (a
# PartyRole choice that's currently unused going forward — treasury.Bank
# is its own model, see the Decision Log) from ever creating an Account.
_SYSTEM_KEY_BY_PARTY_ROLE = {
    "customer": "CUSTOMERS",
    "supplier": "SUPPLIERS",
    "employee": "EMPLOYEES",
    "affiliate": "AFFILIATES",
}


def _load_chart_template(business_type):
    path = CHART_TEMPLATES_DIR / f"{business_type}.json"
    if not path.exists():
        path = CHART_TEMPLATES_DIR / "service.json"
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _create_account_tree(tenant, nodes, parent=None):
    for node in nodes:
        children = node.get("children") or []
        account = Account.objects.create(
            tenant=tenant,
            parent=parent,
            code=node["code"],
            name=node["name"],
            type=node["type"],
            system_key=node.get("system_key", ""),
            is_intercompany=node.get("is_intercompany", False),
            allow_posting=not children,
            is_system=True,
        )
        if children:
            _create_account_tree(tenant, children, parent=account)


def seed_chart_of_accounts(tenant):
    """Create the chart of accounts for a brand-new tenant, from the
    activity-based template matching tenant.business_type (sprint 4.3,
    3.4: "قوالب دليل حسب النشاط ... تُطبَّق عند التسجيل بدل دليل واحد
    للجميع"). Every template lives in apps/accounting/chart_templates/
    as JSON, tagging the accounts other code looks up by meaning
    (system_key) rather than by hardcoded number — see
    get_system_account.
    """
    template = _load_chart_template(tenant.business_type)
    _create_account_tree(tenant, template)


def get_system_account(tenant, system_key):
    """The account tagged with this system_key in the tenant's chart —
    None if the chart has none (e.g. a very old chart from before 4.3
    whose migration backfill didn't map that particular key; callers
    that can't function without one should fall back to
    _LEGACY_FALLBACK_CODES or raise a clear error, not silently post to
    the wrong account)."""
    return Account.objects.filter(tenant=tenant, system_key=system_key).first()


def _get_system_account_or_fallback(tenant, system_key):
    account = get_system_account(tenant, system_key)
    if account is not None:
        return account
    fallback_code = _LEGACY_FALLBACK_CODES.get(system_key)
    if fallback_code:
        account = Account.objects.filter(tenant=tenant, code=fallback_code).first()
    if account is None:
        raise ValidationError(
            _("لا يوجد حساب في الدليل بمفتاح %(key)s — راجع دليل الحسابات.") % {"key": system_key}
        )
    return account


def get_or_create_party_role_account(party, role):
    """Sprint 4.3 (3.4): the sub-ledger/running account for one
    (party, role) pair, auto-created the first time that role is
    created for this party — idempotent (re-checks for an existing
    account first, never creates a duplicate). A party holding two
    roles (e.g. customer + supplier) ends up with two Account rows,
    both with `party` set to it, one under CUSTOMERS and one under
    SUPPLIERS — "الطرف بدورين = حسابان (عملاء/موردين)".

    Returns None (not an error) if the tenant's chart has no parent for
    this role's system_key — an old/custom chart without it simply
    doesn't get sub-ledger automation; the party itself is unaffected.
    """
    system_key = _SYSTEM_KEY_BY_PARTY_ROLE.get(role)
    if system_key is None:
        return None
    existing = Account.objects.filter(
        tenant=party.tenant_id, party=party, parent__system_key=system_key
    ).first()
    if existing is not None:
        return existing
    parent = get_system_account(party.tenant, system_key)
    if parent is None:
        return None
    next_seq = parent.children.count() + 1
    return Account.objects.create(
        tenant=party.tenant,
        parent=parent,
        code=f"{parent.code}.{next_seq:03d}",
        name=party.name,
        type=parent.type,
        allow_posting=True,
        is_system=False,
        party=party,
    )


def get_or_create_treasury_account(instance, system_key):
    """Same idea as get_or_create_party_role_account but for
    Bank/CashBox/Custody, which already carry their own `gl_account` FK
    (sprint 3, "designed nullable-for-now") instead of needing a
    party-style lookup — ARCH_REVIEW_1.md debt #20."""
    if instance.gl_account_id:
        return instance.gl_account
    parent = get_system_account(instance.tenant, system_key)
    if parent is None:
        return None
    next_seq = parent.children.count() + 1
    account = Account.objects.create(
        tenant=instance.tenant,
        parent=parent,
        code=f"{parent.code}.{next_seq:03d}",
        name=instance.name,
        type=parent.type,
        allow_posting=True,
        is_system=False,
    )
    instance.gl_account = account
    instance.save(update_fields=["gl_account"])
    return account


def build_journal_lines_with_fx_rounding(tenant, entry, line_specs, exchange_rate):
    """Sprint 4.2 (3.15.3), extended in 4.3 with the posting guard (3.4:
    "لا ترحيل على حساب له أبناء") and JournalLine.party auto-fill (3.4:
    "auto-filled when posting to a sub-ledger account").

    Converts each line_spec ({"account", "cost_center" (optional),
    "debit_fc", "credit_fc"}, amounts in entry.currency) into an
    unsaved JournalLine with debit/credit (legal_entity.base_currency)
    also populated — each line rounded to the cent independently
    (ROUND_HALF_UP), same as every other money computation in this
    project.

    Converting each line separately can leave the base-currency debit
    and credit totals off by a few cents even though the fc totals are
    exactly balanced (rounding is not linear) — "التوازن إلزامي
    بالعملتين ... وفرق التقريب (≤ 0.05) يُضاف لسطر تقريب تلقائي". A gap
    bigger than that tolerance means a real bug upstream, not rounding
    noise, so it raises instead of silently absorbing it.
    """
    lines = []
    for spec in line_specs:
        account = spec["account"]
        if not account.can_post:
            raise ValidationError(
                _(
                    "لا يمكن الترحيل على الحساب %(code)s: إما أنه حساب أب له فروع "
                    "أو أن الترحيل عليه معطّل."
                )
                % {"code": account.code}
            )
        lines.append(
            JournalLine(
                entry=entry,
                account=account,
                cost_center=spec.get("cost_center"),
                party=account.party,
                debit_fc=spec["debit_fc"],
                credit_fc=spec["credit_fc"],
                debit=(spec["debit_fc"] * exchange_rate).quantize(CENTS, rounding=ROUND_HALF_UP),
                credit=(spec["credit_fc"] * exchange_rate).quantize(CENTS, rounding=ROUND_HALF_UP),
            )
        )

    debit_total = sum((line.debit for line in lines), Decimal("0"))
    credit_total = sum((line.credit for line in lines), Decimal("0"))
    diff = credit_total - debit_total
    if diff != 0:
        if abs(diff) > FX_ROUNDING_TOLERANCE:
            raise ValueError(
                f"FX conversion rounding gap {diff} exceeds the {FX_ROUNDING_TOLERANCE} "
                "tolerance — this indicates a real bug upstream, not rounding noise."
            )
        rounding_account = _get_system_account_or_fallback(tenant, "ROUNDING")
        if diff > 0:
            lines.append(JournalLine(entry=entry, account=rounding_account, debit=diff, credit=Decimal("0")))
        else:
            lines.append(
                JournalLine(entry=entry, account=rounding_account, debit=Decimal("0"), credit=-diff)
            )
    return lines


def _cost_center_revenue_specs(invoice, revenue_account):
    """Sprint 4.4 (ARCH_REVIEW_1.md debt #5, resolved): one revenue
    line per distinct cost_center among the invoice's lines (grouped,
    summed) instead of one aggregated line — "فاتورة ببندين على
    مركزين تولّد سطري إيراد". Lines with no cost_center are grouped
    together under a single None-cost_center line."""
    groups = OrderedDict()
    for line in invoice.lines.select_related("cost_center").order_by("cost_center_id"):
        key = line.cost_center_id
        if key not in groups:
            groups[key] = {"cost_center": line.cost_center, "amount": Decimal("0")}
        groups[key]["amount"] += line.line_subtotal
    return [
        {
            "account": revenue_account,
            "cost_center": group["cost_center"],
            "debit_fc": Decimal("0"),
            "credit_fc": group["amount"],
        }
        for group in groups.values()
    ]


@transaction.atomic
def post_invoice_journal_entry(invoice):
    """Post a balanced journal entry for an issued invoice — created
    directly at status=POSTED (sprint 4.4, 3.15.1): this is a
    system-generated entry, not a manual JV, so it isn't subject to the
    draft/approval workflow — the invoice's own issue() action is
    already the human decision point.

    Debits the customer's own sub-ledger account (auto-created under
    CUSTOMERS, sprint 4.3 — not a shared lump "Accounts Receivable"
    bucket, so per-customer statements/aging can read JournalLine.party
    directly) for the invoice total, credits Sales Revenue (split one
    line per cost center, sprint 4.4) for the subtotal and Tax Payable
    for the tax — always balanced by construction since credit total ==
    debit total (in invoice.currency; build_journal_lines_with_fx_rounding
    handles the base-currency conversion and rounding, sprint 4.2).
    """
    tenant = invoice.tenant
    from apps.parties.models import PartyRole
    from apps.sales.models import Invoice

    ar = get_or_create_party_role_account(invoice.party, PartyRole.Role.CUSTOMER)
    if ar is None:
        ar = _get_system_account_or_fallback(tenant, "CUSTOMERS")
    revenue = _get_system_account_or_fallback(tenant, "SALES")

    entry = JournalEntry.objects.create(
        tenant=tenant,
        legal_entity=invoice.legal_entity,
        date=invoice.issue_date,
        memo=f"Invoice {invoice.number}",
        number=next_document_number(tenant, "journal_entry", invoice.legal_entity, invoice.issue_date),
        status=JournalEntry.Status.POSTED,
        source_type="invoice",
        source_id=invoice.id,
        content_type=ContentType.objects.get_for_model(Invoice),
        object_id=invoice.id,
        currency=invoice.currency,
        exchange_rate=invoice.exchange_rate,
    )

    line_specs = [
        {"account": ar, "debit_fc": invoice.total, "credit_fc": Decimal("0")},
        *_cost_center_revenue_specs(invoice, revenue),
    ]
    if invoice.tax_total:
        tax_payable = _get_system_account_or_fallback(tenant, "VAT_OUTPUT")
        line_specs.append(
            {"account": tax_payable, "debit_fc": Decimal("0"), "credit_fc": invoice.tax_total}
        )

    lines = build_journal_lines_with_fx_rounding(tenant, entry, line_specs, invoice.exchange_rate)
    JournalLine.objects.bulk_create(lines)
    return entry


@transaction.atomic
def void_invoice_journal_entry(invoice):
    """Post a reversing journal entry for a voided (cancelled) invoice —
    docs/SYSTEM_ANALYSIS.md section 4 rule 4: every journal entry stays
    balanced, so voiding never edits or deletes the original entry, it
    posts a mirror-image entry (debit <-> credit swapped per line, same
    accounts and cost centers) that nets it to zero.

    Sprint 4.4: the original flips to REVERSED (a terminal marker, not
    an exclusion — see DocumentStateMixin/REPORTABLE_STATUSES) and the
    new entry is created directly at POSTED, linked back via `reverses`.
    """
    original = JournalEntry.objects.get(
        tenant=invoice.tenant, source_type="invoice", source_id=invoice.id
    )
    reversal = JournalEntry.objects.create(
        tenant=invoice.tenant,
        legal_entity=invoice.legal_entity,
        date=timezone.localdate(),
        memo=f"Void of invoice {invoice.number}",
        number=next_document_number(
            invoice.tenant, "journal_entry", invoice.legal_entity, timezone.localdate()
        ),
        status=JournalEntry.Status.POSTED,
        reverses=original,
        source_type="invoice_void",
        source_id=invoice.id,
        content_type=original.content_type,
        object_id=original.object_id,
        currency=original.currency,
        exchange_rate=original.exchange_rate,
    )
    JournalLine.objects.bulk_create(
        [
            JournalLine(
                entry=reversal,
                account=line.account,
                cost_center=line.cost_center,
                party=line.party,
                debit_fc=line.credit_fc,
                credit_fc=line.debit_fc,
                debit=line.credit,
                credit=line.debit,
            )
            for line in original.lines.all()
        ]
    )
    original.status = JournalEntry.Status.REVERSED
    original.save(update_fields=["status"])
    return reversal


# ---------------------------------------------------------------------
# Sprint 4.4: manual journal entries — "القيود اليدوية" screen. Unlike
# post_invoice_journal_entry (system-generated, straight to POSTED),
# these start at DRAFT and move through the unified status machine
# (DocumentStateMixin) one explicit action at a time.
# ---------------------------------------------------------------------


@transaction.atomic
def create_manual_journal_entry(
    tenant, user, legal_entity, date, line_specs, currency=None, exchange_rate=None, memo="", reference=""
):
    currency = currency or legal_entity.base_currency
    exchange_rate = exchange_rate if exchange_rate is not None else Decimal("1")
    entry = JournalEntry.objects.create(
        tenant=tenant,
        legal_entity=legal_entity,
        date=date,
        memo=memo,
        reference=reference,
        number=next_document_number(tenant, "journal_entry", legal_entity, date),
        status=JournalEntry.Status.DRAFT,
        created_by=user,
        currency=currency,
        exchange_rate=exchange_rate,
    )
    lines = build_journal_lines_with_fx_rounding(tenant, entry, line_specs, exchange_rate)
    JournalLine.objects.bulk_create(lines)
    return entry


def _transition_journal_entry(entry, new_status, user, action):
    old_status = entry.status
    entry.status = new_status
    entry.save(update_fields=["status"])
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER,
        actor_id=user.id,
        action=f"journal_entry.{action}",
        target_type="journal_entry",
        target_id=entry.id,
        tenant_id=entry.tenant_id,
        before={"status": old_status},
        after={"status": new_status},
    )


def _journal_entry_amount_base(entry):
    return entry.lines.aggregate(total=Sum("debit"))["total"] or Decimal("0")


def submit_journal_entry_for_approval(entry, user, request=None):
    """Sprint 4.5: delegates to the generic apps.approvals engine —
    3.15.9's "لا قيد يدوي يُرحَّل بلا اعتماد" is now enforced by a real,
    tenant-editable ApprovalRule (seeded by default at registration and
    backfilled for existing tenants, min_amount=0 -> Owner) instead of
    the hardcoded check 4.4 shipped with."""
    from apps.approvals.services import submit_for_approval

    submit_for_approval(entry, user, "journal_entry", _journal_entry_amount_base(entry), request=request)
    return entry


def approve_journal_entry(entry, user, request=None):
    from apps.approvals.services import approve as approvals_approve

    approvals_approve(entry, user, "journal_entry", _journal_entry_amount_base(entry), request=request)
    return entry


def reject_journal_entry(entry, user, reason, request=None):
    from apps.approvals.services import reject as approvals_reject

    approvals_reject(entry, user, "journal_entry", reason, request=request)
    return entry


def post_journal_entry(entry, user, request=None):
    if entry.status != JournalEntry.Status.APPROVED:
        raise ValidationError(_("Only an approved entry can be posted."))
    _transition_journal_entry(entry, JournalEntry.Status.POSTED, user, "post")


@transaction.atomic
def reverse_journal_entry(entry, user, reason):
    if entry.status != JournalEntry.Status.POSTED:
        raise ValidationError(_("Only a posted entry can be reversed."))
    if not reason:
        raise ValidationError(_("A reason is required to reverse a journal entry."))

    tenant = entry.tenant
    reversal = JournalEntry.objects.create(
        tenant=tenant,
        legal_entity=entry.legal_entity,
        date=timezone.localdate(),
        memo=f"Reversal of {entry.number or entry.id}: {reason}",
        number=next_document_number(tenant, "journal_entry", entry.legal_entity, timezone.localdate()),
        status=JournalEntry.Status.POSTED,
        reverses=entry,
        created_by=user,
        content_type=entry.content_type,
        object_id=entry.object_id,
        currency=entry.currency,
        exchange_rate=entry.exchange_rate,
    )
    JournalLine.objects.bulk_create(
        [
            JournalLine(
                entry=reversal,
                account=line.account,
                cost_center=line.cost_center,
                party=line.party,
                description=line.description,
                debit_fc=line.credit_fc,
                credit_fc=line.debit_fc,
                debit=line.credit,
                credit=line.debit,
            )
            for line in entry.lines.all()
        ]
    )
    entry.status = JournalEntry.Status.REVERSED
    entry.save(update_fields=["status"])
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER,
        actor_id=user.id,
        action="journal_entry.reversed",
        target_type="journal_entry",
        target_id=entry.id,
        tenant_id=tenant.id,
        after={"reason": reason, "reversal_entry_id": str(reversal.id)},
    )
    return reversal


def compute_trial_balance(tenant, legal_entity_id=None, date_from=None, date_to=None):
    """Sprint 4.4 (3.15.1): "ميزان مراجعة أولي" — a UAT verification
    tool, not the full drill-down report (sprint 10). Per leaf account:
    movement debit/credit and balance in base currency. Only POSTED/
    REVERSED entries ever contribute (see REPORTABLE_STATUSES) — total
    debit always equals total credit by construction, since it's
    summing only already-balanced entries."""
    from django.db.models import Sum

    lines = JournalLine.objects.filter(entry__tenant=tenant, entry__status__in=REPORTABLE_STATUSES)
    if legal_entity_id:
        lines = lines.filter(entry__legal_entity_id=legal_entity_id)
    if date_from:
        lines = lines.filter(entry__date__gte=date_from)
    if date_to:
        lines = lines.filter(entry__date__lte=date_to)

    totals = (
        lines.values(
            "account_id", "account__code", "account__name", "account__normal_balance", "account__level"
        )
        .annotate(debit=Sum("debit"), credit=Sum("credit"))
        .order_by("account__code")
    )
    rows = []
    total_debit = total_credit = Decimal("0")
    for row in totals:
        debit = row["debit"] or Decimal("0")
        credit = row["credit"] or Decimal("0")
        is_debit_normal = row["account__normal_balance"] == Account.NormalBalance.DEBIT
        balance = (debit - credit) if is_debit_normal else (credit - debit)
        rows.append(
            {
                "account_id": row["account_id"],
                "account_code": row["account__code"],
                "account_name": row["account__name"],
                "level": row["account__level"],
                "debit": debit,
                "credit": credit,
                "balance": balance,
            }
        )
        total_debit += debit
        total_credit += credit
    return {"rows": rows, "total_debit": total_debit, "total_credit": total_credit}
