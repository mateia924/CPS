"""Sprint 7.0.1 (docs/SYSTEM_ANALYSIS.md §11, rule-11 incident #4):
add_missing_system_accounts used to silently skip a system key when
its spec's exact parent code didn't exist on a tenant's chart — found
live on 13/49 real tenants (fatma/acme among them), five of them
missing GRNI specifically because their chart predates sprint 4.3 and
has no "2000" liability root at all. This block replaces the silent
skip with a declared fallback (first root account of the same type)
and, failing that, a loud, non-zero-exit failure — never a quiet
partial success.
"""

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.accounting.models import Account
from apps.accounting.services import get_required_system_account

from .factories import TenantFactory


def _minimal_legacy_chart(tenant):
    """Same shape as the real fatma/acme: one root account per type,
    none at the code add_missing_system_accounts' specs expect —
    VAT_OUTPUT already tagged on the one liability root, exactly like
    the real tenants (their "2100" root IS the VAT_OUTPUT account)."""
    Account.objects.create(tenant=tenant, code="1000", name="Assets", type="asset", is_system=True)
    Account.objects.create(
        tenant=tenant, code="2100", name="Tax Payable", type="liability",
        is_system=True, system_key="VAT_OUTPUT", allow_manual_posting=False,
    )
    Account.objects.create(tenant=tenant, code="3000", name="Equity", type="equity", is_system=True)
    Account.objects.create(tenant=tenant, code="4000", name="Revenue", type="revenue", is_system=True)
    Account.objects.create(tenant=tenant, code="5000", name="Expense", type="expense", is_system=True)


@pytest.mark.django_db
def test_fallback_by_type_when_exact_parent_code_is_missing():
    tenant = TenantFactory()
    _minimal_legacy_chart(tenant)

    assert not Account.objects.filter(tenant=tenant, code="2000").exists()
    assert not Account.objects.filter(tenant=tenant, system_key="GRNI").exists()

    call_command("add_missing_system_accounts", "--tenant", tenant.subdomain)

    grni = Account.objects.get(tenant=tenant, system_key="GRNI")
    assert grni.parent.code == "2100"  # the declared rule: first root liability account
    assert grni.allow_manual_posting is False

    suppliers = Account.objects.get(tenant=tenant, system_key="SUPPLIERS")
    assert suppliers.parent.code == "2100"

    # A second run against the fallback-placed accounts must still be
    # a true no-op (rule from block 7.0, re-proven for the fallback
    # path specifically).
    before = set(Account.objects.filter(tenant=tenant).values_list("id", "code", "system_key"))
    call_command("add_missing_system_accounts", "--tenant", tenant.subdomain)
    after = set(Account.objects.filter(tenant=tenant).values_list("id", "code", "system_key"))
    assert before == after


@pytest.mark.django_db
def test_fails_loudly_when_no_root_account_of_that_type_exists_at_all():
    """Same shape as the real debug-tenant-x found live: a tenant with
    zero accounts at all — nothing to create anything under, for any
    key. The command must never report success while having quietly
    skipped every single one."""
    tenant = TenantFactory()
    assert not Account.objects.filter(tenant=tenant).exists()

    with pytest.raises(CommandError):
        call_command("add_missing_system_accounts", "--tenant", tenant.subdomain)

    # Genuinely nothing created — a loud failure, not a silent partial
    # success that happens to also create nothing.
    assert not Account.objects.filter(tenant=tenant).exists()


@pytest.mark.django_db
def test_get_required_system_account_raises_naming_the_missing_key():
    tenant = TenantFactory()
    with pytest.raises(ValidationError) as exc_info:
        get_required_system_account(tenant, "GRNI")
    assert "GRNI" in str(exc_info.value)


@pytest.mark.django_db
def test_get_required_system_account_returns_the_account_when_present(tenant_a):
    account = get_required_system_account(tenant_a, "CASH")
    assert account.system_key == "CASH"
