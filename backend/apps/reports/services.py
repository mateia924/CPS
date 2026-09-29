"""Sprint 6.6 (docs/SYSTEM_ANALYSIS.md 3.16.1, sprint-6.md decisions
11-12): the basic financial statements — "بلا Drill-down" (sprint 10
territory). One service, `account_balances()`, is the single source
every report below reads from — same principle as `ledger_lines()`
(5.4)/`compute_trial_balance()` (4.4): no parallel raw SQL, no second
copy of the REPORTABLE_STATUSES query logic.
"""

from datetime import date
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

CENTS = Decimal("0.01")


def _entities_in_scope(legal_entity, include_children):
    """A legal entity and, unless `include_children=False`, every
    descendant in its own sub-tree (3.1's unlimited-depth legal tree)."""
    if not include_children:
        return [legal_entity]
    from apps.organization.models import LegalEntity

    ids = {legal_entity.id}
    frontier = [legal_entity.id]
    while frontier:
        children = list(LegalEntity.objects.filter(parent_id__in=frontier).values_list("id", flat=True))
        new_ids = [c for c in children if c not in ids]
        ids.update(new_ids)
        frontier = new_ids
    return LegalEntity.objects.filter(id__in=ids)


def _level1_ancestor(account):
    """The "بند رئيسي" a line item's subtotal rolls up under — the
    account's own ancestor one level below the chart's type root
    (level 0), or the account itself if it's already there."""
    node = account
    while node.level > 1 and node.parent_id:
        node = node.parent
    return node


def account_balances(tenant, legal_entity=None, include_children=True, date_from=None, date_to=None, cost_center=None):
    """Decision 11: for every *postable* account (a non-leaf chart
    parent never receives a JournalLine directly — 3.4's "لا ترحيل على
    حساب له أبناء" — so it structurally never needs its own row here):
    opening/period debit/period credit/closing, in base currency, same
    REPORTABLE_STATUSES basis as ledger_lines/compute_trial_balance.
    Returns {account_id: {"account", "sign", "opening", "debit",
    "credit", "closing"}}.
    """
    from apps.accounting.models import Account, JournalLine
    from apps.accounting.services import REPORTABLE_STATUSES

    entities = _entities_in_scope(legal_entity, include_children) if legal_entity is not None else None

    lines = JournalLine.objects.filter(entry__tenant=tenant, entry__status__in=REPORTABLE_STATUSES)
    if entities is not None:
        lines = lines.filter(entry__legal_entity__in=entities)
    if cost_center is not None:
        lines = lines.filter(cost_center=cost_center)

    opening_qs = lines.filter(entry__date__lt=date_from) if date_from is not None else lines.none()
    opening_totals = {
        row["account_id"]: row for row in opening_qs.values("account_id").annotate(debit=Sum("debit"), credit=Sum("credit"))
    }

    period_qs = lines
    if date_from is not None:
        period_qs = period_qs.filter(entry__date__gte=date_from)
    if date_to is not None:
        period_qs = period_qs.filter(entry__date__lte=date_to)
    period_totals = {
        row["account_id"]: row for row in period_qs.values("account_id").annotate(debit=Sum("debit"), credit=Sum("credit"))
    }

    # Postable = not referenced as anyone else's parent — the same
    # "leaf" concept Account.is_leaf checks per-instance, done here as
    # one extra query instead of N.
    parent_ids = set(
        Account.objects.filter(tenant=tenant, parent__isnull=False).values_list("parent_id", flat=True)
    )
    accounts = Account.objects.filter(tenant=tenant, is_active=True).exclude(id__in=parent_ids).select_related("parent")

    result = {}
    for account in accounts:
        sign = 1 if account.normal_balance == Account.NormalBalance.DEBIT else -1
        o = opening_totals.get(account.id, {})
        p = period_totals.get(account.id, {})
        o_debit, o_credit = o.get("debit") or Decimal("0"), o.get("credit") or Decimal("0")
        p_debit, p_credit = p.get("debit") or Decimal("0"), p.get("credit") or Decimal("0")
        opening_balance = sign * (o_debit - o_credit)
        closing_balance = sign * ((o_debit + p_debit) - (o_credit + p_credit))
        result[account.id] = {
            "account": account, "sign": sign,
            "opening": opening_balance, "debit": p_debit, "credit": p_credit, "closing": closing_balance,
        }
    return result


def income_statement(tenant, legal_entity=None, include_children=True, date_from=None, date_to=None, cost_center=None):
    """Decision 11: revenue − expense = net income, subtotalled per
    top-level (level-1) parent. Always period-scoped by `debit`/`credit`
    (the movement within [date_from, date_to]) — never `closing`, which
    would double-count anything posted before date_from (this project
    has no year-end closing entry yet — README debt #10 — so revenue/
    expense balances would otherwise carry forward forever)."""
    from apps.accounting.models import Account

    balances = account_balances(tenant, legal_entity, include_children, date_from, date_to, cost_center)
    sections = {Account.Type.REVENUE: {}, Account.Type.EXPENSE: {}}
    for data in balances.values():
        account = data["account"]
        if account.type not in sections:
            continue
        period_net = data["sign"] * (data["debit"] - data["credit"])
        if period_net == 0 and data["debit"] == 0 and data["credit"] == 0:
            continue
        parent = _level1_ancestor(account)
        bucket = sections[account.type].setdefault(
            parent.id, {"account_id": str(parent.id), "code": parent.code, "name": parent.name, "amount": Decimal("0"), "lines": []}
        )
        bucket["amount"] += period_net
        if account.id != parent.id:
            bucket["lines"].append({"account_id": str(account.id), "code": account.code, "name": account.name, "amount": period_net})

    revenue_rows = list(sections[Account.Type.REVENUE].values())
    expense_rows = list(sections[Account.Type.EXPENSE].values())
    total_revenue = sum((r["amount"] for r in revenue_rows), Decimal("0"))
    total_expense = sum((r["amount"] for r in expense_rows), Decimal("0"))
    return {
        "revenue": revenue_rows, "expense": expense_rows,
        "total_revenue": total_revenue, "total_expense": total_expense,
        "net_income": total_revenue - total_expense,
    }


def balance_sheet(tenant, legal_entity=None, include_children=True, as_of=None, cost_center=None):
    """Decision 11: assets = liabilities + equity + "نتيجة الفترات غير
    المقفلة" (net income since inception up to `as_of`, reusing
    income_statement itself — the identity balances structurally by
    double-entry construction, not by a plug)."""
    from apps.accounting.models import Account

    as_of = as_of or timezone.localdate()
    balances = account_balances(tenant, legal_entity, include_children, date_from=None, date_to=as_of, cost_center=cost_center)
    sections = {Account.Type.ASSET: [], Account.Type.LIABILITY: [], Account.Type.EQUITY: []}
    for data in balances.values():
        account = data["account"]
        if account.type not in sections or data["closing"] == 0:
            continue
        sections[account.type].append({"account_id": str(account.id), "code": account.code, "name": account.name, "amount": data["closing"]})

    net_income = income_statement(tenant, legal_entity, include_children, date_from=None, date_to=as_of, cost_center=cost_center)[
        "net_income"
    ]
    equity_rows = sections[Account.Type.EQUITY]
    if net_income != 0:
        equity_rows = equity_rows + [
            {"account_id": None, "code": "", "name": str(_("نتيجة الفترات غير المقفلة")), "amount": net_income}
        ]

    total_assets = sum((r["amount"] for r in sections[Account.Type.ASSET]), Decimal("0"))
    total_liabilities = sum((r["amount"] for r in sections[Account.Type.LIABILITY]), Decimal("0"))
    total_equity = sum((r["amount"] for r in equity_rows), Decimal("0"))
    # Sprint 6.5.15 (UAT item 2): "الأصول = الخصوم + حقوق الملكية" —
    # a real check, not just a display label. Double-entry construction
    # already guarantees this holds whenever every account's sign is
    # correct (see the normal_balance backfill this same block ships
    # with); a nonzero difference means a real data problem upstream,
    # never a footer to silently omit.
    difference = total_assets - (total_liabilities + total_equity)
    return {
        "assets": sections[Account.Type.ASSET], "liabilities": sections[Account.Type.LIABILITY], "equity": equity_rows,
        "total_assets": total_assets, "total_liabilities": total_liabilities, "total_equity": total_equity,
        "is_balanced": difference == 0, "difference": difference,
        "as_of": as_of,
    }


def _aging_bucket(days_overdue):
    if days_overdue <= 30:
        return "0-30"
    if days_overdue <= 60:
        return "31-60"
    if days_overdue <= 90:
        return "61-90"
    return "90+"


def aging_report(tenant, legal_entity=None, as_of=None):
    """Decision 12: open invoices (balance_fc > 0) + the open items
    recorded on an approved opening balance's party lines (marked
    "افتتاحي"), bucketed by days overdue from due_date (falling back to
    issue_date), converted to base currency at each document's own
    historical rate — never today's."""
    from apps.accounting.models import OpeningBalanceEntry, OpeningBalanceLine
    from apps.sales.models import Invoice

    as_of = as_of or timezone.localdate()
    entities = _entities_in_scope(legal_entity, True) if legal_entity is not None else None

    rows = []
    per_party = {}

    def _add(party_id, party_name, source, reference, due_date, amount_base, is_opening):
        days = (as_of - due_date).days
        rows.append(
            {
                "party_id": str(party_id), "party_name": party_name, "source": source, "reference": reference,
                "due_date": due_date, "amount_base": amount_base, "bucket": _aging_bucket(days), "is_opening": is_opening,
            }
        )
        entry = per_party.setdefault(party_id, {"party_name": party_name, "amount_base": Decimal("0")})
        entry["amount_base"] += amount_base

    invoices = Invoice.objects.filter(tenant=tenant, status=Invoice.Status.ISSUED, balance_fc__gt=0).select_related("party")
    if entities is not None:
        invoices = invoices.filter(legal_entity__in=entities)
    for invoice in invoices:
        due = invoice.due_date or invoice.issue_date
        amount_base = (invoice.balance_fc * invoice.exchange_rate).quantize(CENTS)
        _add(invoice.party_id, invoice.party.name, "invoice", invoice.number, due, amount_base, False)

    ob_lines = OpeningBalanceLine.objects.filter(
        entry__tenant=tenant, entry__status=OpeningBalanceEntry.Status.APPROVED,
        party__isnull=False, open_items__isnull=False,
    ).select_related("party", "entry")
    if entities is not None:
        ob_lines = ob_lines.filter(entry__legal_entity__in=entities)
    for line in ob_lines:
        for item in line.open_items:
            item_date = date.fromisoformat(item["date"])
            amount_fc = Decimal(str(item["amount_fc"]))
            amount_base = (amount_fc * line.exchange_rate).quantize(CENTS)
            _add(line.party_id, line.party.name, "opening_balance", item["ref"], item_date, amount_base, True)

    totals_by_party = [
        {"party_id": str(pid), "party_name": v["party_name"], "amount_base": v["amount_base"]}
        for pid, v in per_party.items()
    ]
    total = sum((v["amount_base"] for v in per_party.values()), Decimal("0"))
    return {"rows": rows, "totals_by_party": totals_by_party, "total": total, "as_of": as_of}


def fixed_assets_register(tenant, as_of=None, legal_entity=None, include_children=True):
    """Sprint 6.5 (decision 13): the fixed-asset register report —
    per-asset cost/additions/disposals/accumulated depreciation/book
    value/remaining months, plus a reconciliation footer against the
    ledger using the exact same shared function the period-close
    checklist's own WARN reads (apps.assets.reconciliation.
    register_vs_ledger) — the two can never silently disagree. A fully
    DISPOSED asset is no longer a live line item, same exclusion
    register_vs_ledger's own totals already apply.
    """
    from django.db.models import Sum

    from apps.assets.depreciation import current_book_value
    from apps.assets.models import Asset
    from apps.assets.reconciliation import register_vs_ledger

    as_of = as_of or timezone.localdate()
    assets = (
        Asset.objects.filter(tenant=tenant, is_active=True, purchase_date__lte=as_of)
        .exclude(status=Asset.Status.DISPOSED)
        .select_related("depreciation_entry")
    )
    if legal_entity is not None:
        assets = assets.filter(legal_entity__in=_entities_in_scope(legal_entity, include_children))

    rows = []
    total_cost = Decimal("0")
    total_additions = Decimal("0")
    total_disposals = Decimal("0")
    total_accumulated = Decimal("0")
    total_book_value = Decimal("0")
    for asset in assets.order_by("code"):
        additions_total = asset.additions.aggregate(total=Sum("amount_base"))["total"] or Decimal("0")
        disposals_total = asset.disposals.aggregate(total=Sum("cost_share"))["total"] or Decimal("0")
        remaining_fraction = Decimal("1") - asset.disposed_fraction
        cost_base = asset.cost_base if asset.cost_base is not None else asset.purchase_cost
        remaining_cost = (cost_base * remaining_fraction).quantize(CENTS)
        book_value = current_book_value(asset)
        accumulated = remaining_cost - book_value
        remaining_months = 0
        if asset.depreciation_entry_id:
            remaining_months = asset.depreciation_entry.installments.filter(status="due").count()

        rows.append(
            {
                "asset_id": str(asset.id), "code": asset.code, "name": asset.name, "category": asset.category,
                "in_service_date": asset.in_service_date or asset.purchase_date,
                "depreciation_method": asset.depreciation_method,
                "cost": asset.purchase_cost, "additions": additions_total, "disposals": disposals_total,
                "accumulated_depreciation": accumulated, "book_value": book_value,
                "remaining_months": remaining_months, "status": asset.status,
            }
        )
        total_cost += asset.purchase_cost
        total_additions += additions_total
        total_disposals += disposals_total
        total_accumulated += accumulated
        total_book_value += book_value

    reconciliation = register_vs_ledger(tenant, as_of=as_of, legal_entity=legal_entity, include_children=include_children)
    return {
        "rows": rows,
        "totals": {
            "cost": total_cost, "additions": total_additions, "disposals": total_disposals,
            "accumulated_depreciation": total_accumulated, "book_value": total_book_value,
        },
        "reconciliation": reconciliation,
        "as_of": as_of,
    }
