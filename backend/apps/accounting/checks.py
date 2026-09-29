"""Sprint 6.5.17 (UAT item 1): a chart-of-accounts row with a blank
`type` or `normal_balance` is exactly the bug behind the balance-sheet
sign errors found on tenant "fatma" (migrations 0006/0016/0022/0027
backfilled six system accounts via the historical model, which skips
the live Account.save()'s own defaulting). Migration 0032 backfills
every existing row; this check makes a future recurrence (a new write
path that bypasses save(), a bulk_create, a future migration written
the same broken way) fail loudly at `manage.py check` instead of
silently corrupting a report months later.
"""

from django.core.checks import Error, register
from django.db import DatabaseError


@register()
def check_no_blank_account_type_or_normal_balance(app_configs, **kwargs):
    from .models import Account

    try:
        bad = list(
            Account.objects.filter(type="").values_list("tenant__subdomain", "code")
        ) + list(
            Account.objects.filter(normal_balance="").values_list("tenant__subdomain", "code")
        )
    except DatabaseError:
        # A brand-new database (accounting_account doesn't exist yet,
        # before the first `migrate` ever runs) — nothing to check.
        return []

    if not bad:
        return []

    examples = ", ".join(f"{subdomain}:{code}" for subdomain, code in bad[:10])
    more = f" (+{len(bad) - 10} أخرى)" if len(bad) > 10 else ""
    return [
        Error(
            f"{len(bad)} حساب(ات) بحقل type أو normal_balance فارغ — يكسر أي تقرير يعتمد عليهما: {examples}{more}",
            hint="شغّل migration accounting/0032، أو صحِّح الحساب يدويًا (النوع/الطبيعة من جذر الشجرة).",
            id="accounting.E001",
        )
    ]
