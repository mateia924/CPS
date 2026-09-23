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
