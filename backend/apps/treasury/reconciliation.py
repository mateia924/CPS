"""Sprint 5.5 (block 5.5.2, v2 decisions 1-3): the automatic + manual
matching engine — links a BankStatementLine to one or more POSTED
JournalLine rows on the bank's own gl_account. Never creates a journal
entry itself (decision 1: "لا مسار يُنشئ قيدًا من داخل محرك المطابقة
نفسه") — see apps.treasury.views for the "سند من هذا البند" flow that
creates a voucher first and matches it afterward.
"""

import datetime
from decimal import Decimal
from difflib import SequenceMatcher

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounting.models import JournalEntry, JournalLine
from apps.platform.models import AuditLog
from apps.platform.services import log_action

from .models import BankStatementLine

# Fixed for this sprint, not a per-tenant setting (v2 decision 2).
MATCH_DATE_WINDOW_DAYS = 2


def find_candidates(statement_line):
    """POSTED JournalLine rows on the statement's bank account, not
    already bound to another statement line, with the same signed net
    amount (debit_fc - credit_fc) in the bank's own currency and a
    date within MATCH_DATE_WINDOW_DAYS — sorted by date proximity then
    description similarity (never a hard filter, only a tie-breaker)."""
    bank = statement_line.statement.bank
    account = bank.gl_account
    if account is None:
        return []
    date_from = statement_line.date - datetime.timedelta(days=MATCH_DATE_WINDOW_DAYS)
    date_to = statement_line.date + datetime.timedelta(days=MATCH_DATE_WINDOW_DAYS)
    candidates = JournalLine.objects.filter(
        entry__tenant_id=statement_line.tenant_id,
        entry__status=JournalEntry.Status.POSTED,
        account=account,
        bank_statement_line__isnull=True,
        entry__date__gte=date_from,
        entry__date__lte=date_to,
    ).select_related("entry")
    signed = [line for line in candidates if (line.debit_fc - line.credit_fc) == statement_line.amount]

    def sort_key(line):
        date_diff = abs((line.entry.date - statement_line.date).days)
        text = line.description or line.entry.memo or ""
        similarity = SequenceMatcher(None, text, statement_line.description or "").ratio()
        return (date_diff, -similarity)

    return sorted(signed, key=sort_key)


def matched_lines_warning(entry):
    """v2 decision 10: reversing an entry with a MATCHED bank line is
    allowed (the bank really did move the money) — the match stays on
    the original (now-REVERSED) line, and the new reversal line is a
    fresh, unmatched row by construction. Callers surface this as a
    warning, never a block."""
    if entry.lines.filter(bank_statement_line__isnull=False).exists():
        return [
            str(
                _(
                    "This entry has a reconciled bank line — the match will "
                    "stay on the original line; the reversal itself is not "
                    "matched to the statement."
                )
            )
        ]
    return []


@transaction.atomic
def auto_match_statement(statement, user=None):
    """Runs right after import (block 5.5.1's import_bank_statement).
    A statement line with exactly one candidate is matched
    automatically; more than one or none is left UNMATCHED for manual
    review — never a guess (decision 2)."""
    matched_count = 0
    for line in statement.lines.filter(status=BankStatementLine.Status.UNMATCHED):
        candidates = find_candidates(line)
        if len(candidates) == 1:
            _apply_match(line, [candidates[0]], matched_by=BankStatementLine.MatchedBy.AUTO, user=user)
            matched_count += 1
    return matched_count


def _apply_match(statement_line, journal_lines, matched_by, user):
    now = timezone.now()
    for journal_line in journal_lines:
        journal_line.bank_statement_line = statement_line
        journal_line.reconciled_at = now
        journal_line.reconciled_by = user
        journal_line.save(update_fields=["bank_statement_line", "reconciled_at", "reconciled_by"])
    statement_line.status = BankStatementLine.Status.MATCHED
    statement_line.matched_by = matched_by
    statement_line.matched_by_user = user
    statement_line.matched_at = now
    statement_line.save(update_fields=["status", "matched_by", "matched_by_user", "matched_at"])


@transaction.atomic
def manual_match(statement_line, journal_line_ids, user, request=None):
    """v2 decision 4: N journal lines may match one statement line
    (grouped deposit, or a receipt plus a bank-fee payment) as long as
    their combined signed net amount equals the statement line's
    amount exactly — the reverse (one journal line matching several
    statement lines) is impossible by construction (a single FK
    column)."""
    if statement_line.status != BankStatementLine.Status.UNMATCHED:
        raise ValidationError({"detail": [_("This statement line is not unmatched.")]})

    bank = statement_line.statement.bank
    lines = list(
        JournalLine.objects.filter(
            id__in=journal_line_ids, entry__tenant_id=statement_line.tenant_id,
            entry__status=JournalEntry.Status.POSTED, account=bank.gl_account,
            bank_statement_line__isnull=True,
        ).select_related("entry")
    )
    if len(lines) != len(set(journal_line_ids)):
        raise ValidationError(
            {"journal_line_ids": [_("One or more journal lines were not found, already matched, or not POSTED on this bank account.")]}
        )
    total = sum((line.debit_fc - line.credit_fc for line in lines), Decimal("0"))
    if total != statement_line.amount:
        raise ValidationError(
            {
                "journal_line_ids": [
                    str(
                        _("Selected lines sum to %(total)s, which does not equal the statement line's amount (%(amount)s).")
                        % {"total": total, "amount": statement_line.amount}
                    )
                ]
            }
        )

    _apply_match(statement_line, lines, matched_by=BankStatementLine.MatchedBy.MANUAL, user=user)
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER, actor_id=user.id if user else None,
        action="bank_statement_line.matched", target_type="bank_statement_line",
        target_id=statement_line.id, tenant_id=statement_line.tenant_id,
        after={"journal_line_ids": [str(line.id) for line in lines], "matched_by": "manual"},
        request=request,
    )
    return statement_line


@transaction.atomic
def unmatch(statement_line, user, request=None):
    journal_lines = list(statement_line.journal_lines.all())
    for journal_line in journal_lines:
        journal_line.bank_statement_line = None
        journal_line.reconciled_at = None
        journal_line.reconciled_by = None
        journal_line.save(update_fields=["bank_statement_line", "reconciled_at", "reconciled_by"])
    statement_line.status = BankStatementLine.Status.UNMATCHED
    statement_line.matched_by = ""
    statement_line.matched_by_user = None
    statement_line.matched_at = None
    statement_line.ignored_reason = ""
    statement_line.save(
        update_fields=["status", "matched_by", "matched_by_user", "matched_at", "ignored_reason"]
    )
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER, actor_id=user.id if user else None,
        action="bank_statement_line.unmatched", target_type="bank_statement_line",
        target_id=statement_line.id, tenant_id=statement_line.tenant_id,
        before={"journal_line_ids": [str(line.id) for line in journal_lines]}, request=request,
    )
    return statement_line


def reconciliation_report(tenant, bank, as_of=None):
    """v2 decision 9 — "بصيغة المدقق" (two adjusted sides, not a plain
    opening+pending−pending): the bank's own latest statement closing
    balance adjusted for what the books don't show yet, vs. the book
    balance adjusted for what the bank hasn't shown yet. Both should
    land on the same number; the difference is always displayed, never
    hidden when nonzero. Everything is in the bank's own currency
    (ledger_lines' *_fc figures), the base-currency amount is display
    only."""
    from apps.accounting.services import ledger_lines

    from .models import BankStatement, BankStatementLine

    as_of = as_of or timezone.now().date()
    account = bank.gl_account

    latest_statement = (
        BankStatement.objects.filter(tenant=tenant, bank=bank, period_end__lte=as_of)
        .order_by("-period_end")
        .first()
    )
    statement_closing_balance = latest_statement.closing_balance if latest_statement else Decimal("0")

    if account is None:
        ledger = {"closing_balance_fc": Decimal("0")}
        outstanding_deposits, outstanding_payments = [], []
    else:
        ledger = ledger_lines(tenant, account, date_to=as_of)
        unmatched_lines = JournalLine.objects.filter(
            entry__tenant=tenant, entry__status=JournalEntry.Status.POSTED, account=account,
            bank_statement_line__isnull=True, entry__date__lte=as_of,
        ).select_related("entry")
        outstanding_deposits = [
            {"date": jl.entry.date, "entry_id": str(jl.entry_id), "entry_number": jl.entry.number,
             "description": jl.description or jl.entry.memo, "amount": jl.debit_fc - jl.credit_fc}
            for jl in unmatched_lines if (jl.debit_fc - jl.credit_fc) > 0
        ]
        outstanding_payments = [
            {"date": jl.entry.date, "entry_id": str(jl.entry_id), "entry_number": jl.entry.number,
             "description": jl.description or jl.entry.memo, "amount": jl.debit_fc - jl.credit_fc}
            for jl in unmatched_lines if (jl.debit_fc - jl.credit_fc) < 0
        ]

    bank_side_adjustment = sum((d["amount"] for d in outstanding_deposits), Decimal("0")) + sum(
        (p["amount"] for p in outstanding_payments), Decimal("0")
    )
    bank_adjusted = statement_closing_balance + bank_side_adjustment

    all_statement_ids = BankStatement.objects.filter(tenant=tenant, bank=bank).values_list("id", flat=True)
    pending_statement_lines = BankStatementLine.objects.filter(
        tenant=tenant, statement_id__in=all_statement_ids, date__lte=as_of,
        status__in=[BankStatementLine.Status.UNMATCHED, BankStatementLine.Status.IGNORED],
    )
    unrecorded_credits = [
        {"id": str(sl.id), "date": sl.date, "description": sl.description, "amount": sl.amount, "status": sl.status}
        for sl in pending_statement_lines if sl.amount > 0
    ]
    unrecorded_debits = [
        {"id": str(sl.id), "date": sl.date, "description": sl.description, "amount": sl.amount, "status": sl.status}
        for sl in pending_statement_lines if sl.amount < 0
    ]
    ignored_items = [
        {"id": str(sl.id), "date": sl.date, "description": sl.description, "amount": sl.amount}
        for sl in pending_statement_lines if sl.status == BankStatementLine.Status.IGNORED
    ]
    book_side_adjustment = sum((c["amount"] for c in unrecorded_credits), Decimal("0")) + sum(
        (d["amount"] for d in unrecorded_debits), Decimal("0")
    )
    book_adjusted = ledger["closing_balance_fc"] + book_side_adjustment

    total_lines = BankStatementLine.objects.filter(tenant=tenant, statement_id__in=all_statement_ids)
    total_count = total_lines.count()
    settled_count = total_lines.exclude(status=BankStatementLine.Status.UNMATCHED).count()

    return {
        "as_of": as_of,
        "currency": bank.currency,
        "bank_closing_balance": statement_closing_balance,
        "outstanding_deposits": outstanding_deposits,
        "outstanding_payments": outstanding_payments,
        "bank_adjusted_balance": bank_adjusted,
        "book_closing_balance": ledger["closing_balance_fc"],
        "unrecorded_credits": unrecorded_credits,
        "unrecorded_debits": unrecorded_debits,
        "ignored_items": ignored_items,
        "book_adjusted_balance": book_adjusted,
        "difference": bank_adjusted - book_adjusted,
        "reconciled_ratio": round(settled_count / total_count, 4) if total_count else 0.0,
        "latest_statement_id": str(latest_statement.id) if latest_statement else None,
    }


def reconciliation_dashboard(tenant, as_of=None):
    """Sprint 6.9 (sprint-6.md, "التسوية البنكية" — a debt from 5.5.2:
    reconciliation_report() above already computes everything per bank,
    but the only surface that ever called it was one bank's own detail
    page — there was no single screen showing every bank's
    reconciliation status at a glance. One row per active bank, same
    numbers reconciliation_report already returns, just summarized."""
    from .models import Bank, BankStatement

    as_of = as_of or timezone.now().date()
    rows = []
    for bank in Bank.objects.filter(tenant=tenant, is_active=True).order_by("name"):
        report = reconciliation_report(tenant, bank, as_of=as_of)
        latest_statement = (
            BankStatement.objects.filter(tenant=tenant, bank=bank, period_end__lte=as_of)
            .order_by("-period_end")
            .first()
        )
        rows.append(
            {
                "bank_id": str(bank.id),
                "bank_name": bank.name,
                "currency": report["currency"],
                "last_statement_end": latest_statement.period_end if latest_statement else None,
                "reconciled_ratio": report["reconciled_ratio"],
                "unmatched_statement_items": len(report["unrecorded_credits"]) + len(report["unrecorded_debits"]),
                "unmatched_book_lines": len(report["outstanding_deposits"]) + len(report["outstanding_payments"]),
                "difference": report["difference"],
                "has_statement": latest_statement is not None,
            }
        )
    return rows


@transaction.atomic
def ignore_line(statement_line, reason, user, request=None):
    if statement_line.status != BankStatementLine.Status.UNMATCHED:
        raise ValidationError({"detail": [_("Only an unmatched line can be ignored.")]})
    if not reason:
        raise ValidationError({"reason": [_("A reason is required to ignore a statement line.")]})
    statement_line.status = BankStatementLine.Status.IGNORED
    statement_line.ignored_reason = reason
    statement_line.save(update_fields=["status", "ignored_reason"])
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER, actor_id=user.id if user else None,
        action="bank_statement_line.ignored", target_type="bank_statement_line",
        target_id=statement_line.id, tenant_id=statement_line.tenant_id,
        after={"reason": reason}, request=request,
    )
    return statement_line
