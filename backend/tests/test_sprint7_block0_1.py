"""Sprint 7.0.1/7.0.2 (docs/SYSTEM_ANALYSIS.md §11, rule-11 incidents
#4 and #5): add_missing_system_accounts used to silently skip a system
key when its spec's exact parent code didn't exist on a tenant's chart
— found live on 13/49 real tenants (fatma/acme among them), missing
GRNI because their chart predates sprint 4.3 and has no "2000"
liability root at all (7.0.1, incident #4).

7.0.1's own fix — fall back to "the first root account of the same
type" — was itself the next incident (#5): on fatma/acme's real chart,
that root was VAT_OUTPUT, an ACTIVE-POSTING LEAF account every invoice
posts to directly. The moment it gained a child, Account.can_post
(which depends on is_leaf, a live computed property — not a stored
flag) went False for it, breaking every new invoice for 12 real
tenants live, for hours, undetected until a before/after audit asked
about the computed property specifically rather than just the stored
flag. The equity root (account 3000) suffered the identical fate from
an earlier run the same day. Both were corrected on the live database
via a one-off, documented, AuditLog-logged deletion of the zero-
journal-line rows that caused it (apps.accounting.management.commands.
emergency_delete_regressed_accounts) before this redesign landed.

7.0.2's fix: the fallback NEVER attaches a new child to an account
that already exists, period. It creates a brand-new, never-postable
category account at the expected parent code instead — a node with
zero history can never regress an existing posting path.
"""

from io import StringIO

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.accounting.models import Account
from apps.accounting.services import get_required_system_account
from apps.tenants.models import Tenant

from .factories import TenantFactory


def _minimal_legacy_chart(tenant):
    """Same shape as the real fatma/acme: one root account per type,
    none at the code add_missing_system_accounts' specs expect —
    VAT_OUTPUT tagged directly on the one liability root (a real,
    active-posting LEAF — not a category header), exactly like the
    real tenants whose "2100" root IS the VAT_OUTPUT account itself."""
    Account.objects.create(tenant=tenant, code="1000", name="Assets", type="asset", is_system=True)
    Account.objects.create(
        tenant=tenant, code="2100", name="Tax Payable", type="liability",
        is_system=True, system_key="VAT_OUTPUT", allow_manual_posting=False,
    )
    Account.objects.create(tenant=tenant, code="3000", name="Equity", type="equity", is_system=True)
    Account.objects.create(tenant=tenant, code="4000", name="Revenue", type="revenue", is_system=True)
    Account.objects.create(tenant=tenant, code="5000", name="Expense", type="expense", is_system=True)


@pytest.mark.django_db
def test_running_the_command_never_changes_can_post_for_any_pre_existing_account():
    """The most important test from this incident (the owner's own
    framing): captures the set of pre-existing accounts' can_post
    state before running the command and again after, on the exact
    chart shape that broke live — and fails on ANY change. This single
    test would have caught the entire incident before it ever reached
    a real tenant."""
    tenant = TenantFactory()
    _minimal_legacy_chart(tenant)

    pre_existing_ids = list(Account.objects.filter(tenant=tenant).values_list("id", flat=True))
    before = {pk: Account.objects.get(pk=pk).can_post for pk in pre_existing_ids}

    call_command("add_missing_system_accounts", "--tenant", tenant.subdomain)

    after = {pk: Account.objects.get(pk=pk).can_post for pk in pre_existing_ids}
    assert before == after


@pytest.mark.django_db
def test_fallback_creates_a_new_category_node_never_reuses_an_existing_account():
    tenant = TenantFactory()
    _minimal_legacy_chart(tenant)

    vat_output = Account.objects.get(tenant=tenant, system_key="VAT_OUTPUT")
    assert vat_output.can_post is True  # it's a real, active-posting leaf before the run

    assert not Account.objects.filter(tenant=tenant, code="2000").exists()
    assert not Account.objects.filter(tenant=tenant, system_key="GRNI").exists()

    call_command("add_missing_system_accounts", "--tenant", tenant.subdomain)

    grni = Account.objects.get(tenant=tenant, system_key="GRNI")
    new_category = Account.objects.get(tenant=tenant, code="2000")
    assert grni.parent_id == new_category.id
    assert new_category.allow_posting is False
    assert new_category.allow_manual_posting is False
    assert grni.allow_manual_posting is False

    # The whole point: VAT_OUTPUT is never touched, never gains a
    # child, and stays exactly as postable as it was before.
    vat_output.refresh_from_db()
    assert vat_output.children.count() == 0
    assert vat_output.can_post is True

    suppliers = Account.objects.get(tenant=tenant, system_key="SUPPLIERS")
    assert suppliers.parent_id == new_category.id

    # Idempotent: a second run changes nothing.
    before = set(Account.objects.filter(tenant=tenant).values_list("id", "code", "system_key"))
    call_command("add_missing_system_accounts", "--tenant", tenant.subdomain)
    after = set(Account.objects.filter(tenant=tenant).values_list("id", "code", "system_key"))
    assert before == after


@pytest.mark.django_db
def test_never_attaches_to_an_existing_account_even_when_it_sits_at_the_expected_code():
    """The owner's own sharper follow-up: what if the EXPECTED parent
    code ("2000") itself already exists as a real, active-posting leaf
    — not missing, not the fallback path, the exact-match path? None
    of the 12 real tenants happened to have this shape (their "2000"
    was simply absent), but the command must never assume that — the
    invariant ("never attach a child to a currently-postable account")
    has to hold regardless of which code the danger shows up at."""
    tenant = TenantFactory()
    _minimal_legacy_chart(tenant)
    # Make "2000" itself a second genuine active-posting leaf — not a
    # category header — exactly the shape that would have reproduced
    # tonight's incident on a DIFFERENT code if the fix only special-
    # cased "2100".
    danger_leaf = Account.objects.create(
        tenant=tenant, code="2000", name="حساب نشط", type="liability",
        is_system=False, allow_posting=True, allow_manual_posting=True,
    )
    assert danger_leaf.can_post is True

    call_command("add_missing_system_accounts", "--tenant", tenant.subdomain)

    danger_leaf.refresh_from_db()
    # Never modified, never gains a child, stays exactly as postable.
    assert danger_leaf.parent_id is None
    assert danger_leaf.children.count() == 0
    assert danger_leaf.can_post is True

    # GRNI/SUPPLIERS land under some OTHER, freshly created node — not
    # "2000", since "2000" was unsafe to use.
    grni = Account.objects.get(tenant=tenant, system_key="GRNI")
    assert grni.parent_id != danger_leaf.id
    assert grni.parent.allow_posting is False
    assert grni.parent.can_post is False


@pytest.mark.django_db
def test_zero_account_tenant_gets_a_full_fresh_tree_with_no_failures():
    """Same shape as the real debug-tenant-x found live (zero accounts
    at all) — under 7.0.2's design this is no longer a failure case:
    every category root is created fresh on demand, so there is never
    an existing account to reuse (and therefore never anything to
    regress) regardless of how empty the starting chart is."""
    tenant = TenantFactory()
    assert not Account.objects.filter(tenant=tenant).exists()

    call_command("add_missing_system_accounts", "--tenant", tenant.subdomain)

    created = Account.objects.filter(tenant=tenant)
    assert created.exists()
    category_roots = created.filter(parent__isnull=True)
    for root in category_roots:
        assert root.allow_posting is False, f"{root.code} should be a non-postable category root"


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


@pytest.mark.django_db
def test_archived_tenant_with_zero_accounts_is_excluded_not_failed():
    """Sprint 7.0.1 follow-up (the generalization the real debug-
    tenant-x archiving required): an archived tenant must not be
    processed at all, but must be named in the excluded-tenants line,
    not silently dropped either."""
    tenant = TenantFactory(subdomain="archived-empty-tenant")
    tenant.status = Tenant.Status.ARCHIVED
    tenant.save(update_fields=["status"])
    assert not Account.objects.filter(tenant=tenant).exists()

    out = StringIO()
    call_command("add_missing_system_accounts", "--tenant", tenant.subdomain, stdout=out)

    assert "archived-empty-tenant" in out.getvalue()
    assert "Excluding 1 archived tenant" in out.getvalue()
    assert not Account.objects.filter(tenant=tenant).exists()


# --- check_chart_health (the standing diagnostic from this incident) ---
# Reproduces, structurally, the real and STILL LIVE latent incident
# this exercise surfaced: migration 0027 (sprint 6.5, 2026-09-26) gave
# SALES (account "4000") a child (DISPOSAL_GAIN_LOSS) on fatma/acme/
# sprint15test — each of which already had real invoice postings
# directly on "4000" from before. can_post went False with no event
# logged anywhere; none of the three has issued a new invoice since,
# so nobody has hit it in over a week.


def _post_a_line_on_sales(tenant):
    from apps.accounting.models import JournalEntry, JournalLine
    from apps.organization.models import LegalEntity

    branch = LegalEntity.objects.get(tenant=tenant, entity_type=LegalEntity.Type.BRANCH)
    sales = Account.objects.get(tenant=tenant, system_key="SALES")
    cash = Account.objects.get(tenant=tenant, system_key="CASH")
    entry = JournalEntry.objects.create(
        tenant=tenant, legal_entity=branch, date="2026-01-01", status=JournalEntry.Status.POSTED,
        produced_by=JournalEntry.ProducedBy.MANUAL,
    )
    JournalLine.objects.create(entry=entry, account=cash, debit=100, credit=0)
    JournalLine.objects.create(entry=entry, account=sales, debit=0, credit=100)
    return sales


@pytest.mark.django_db
def test_check_chart_health_finds_a_disabled_automated_posting_path(tenant_a):
    sales = _post_a_line_on_sales(tenant_a)
    Account.objects.create(tenant=tenant_a, code="4999", name="child", type="revenue", parent=sales)
    assert sales.can_post is False

    out = StringIO()
    with pytest.raises(CommandError):
        call_command("check_chart_health", "--fail-on-findings", stdout=out)
    assert tenant_a.subdomain in out.getvalue()
    assert "SALES" in out.getvalue()

    out_no_fail = StringIO()
    call_command("check_chart_health", stdout=out_no_fail)  # must not raise without the flag
    assert tenant_a.subdomain in out_no_fail.getvalue()


@pytest.mark.django_db
def test_check_chart_health_reports_nothing_for_a_healthy_chart(tenant_a):
    out = StringIO()
    call_command("check_chart_health", "--fail-on-findings", stdout=out)  # must not raise
    assert "0 findings" in out.getvalue()


@pytest.mark.django_db
def test_check_chart_health_ignores_an_account_that_was_always_just_a_category_header():
    """A plain category header (no JournalLine of its own, ever) must
    never be reported — only an account that was once a real, directly
    -posted-to leaf and silently lost that ability is a finding."""
    tenant = TenantFactory()
    _minimal_legacy_chart(tenant)
    call_command("add_missing_system_accounts", "--tenant", tenant.subdomain)

    out = StringIO()
    call_command("check_chart_health", "--fail-on-findings", stdout=out)  # must not raise
    assert "0 findings" in out.getvalue()


@pytest.mark.django_db
def test_check_chart_health_accepted_exception_is_printed_but_does_not_fail(tenant_a, tmp_path, monkeypatch):
    """A committed exception (docs/ops/chart_health_exceptions.json)
    still shows up in the output every run — never a silent skip —
    but no longer counts toward --fail-on-findings."""
    import apps.accounting.management.commands.check_chart_health as cch

    tenant = tenant_a
    sales = _post_a_line_on_sales(tenant)
    Account.objects.create(tenant=tenant, code="4999", name="child", type="revenue", parent=sales)

    exceptions_file = tmp_path / "chart_health_exceptions.json"
    exceptions_file.write_text(
        '{"exceptions": [{"tenant": "%s", "system_key": "SALES", "reason": "test", '
        '"date": "2026-10-04", "decided_by": "test"}]}' % tenant.subdomain,
        encoding="utf-8",
    )
    monkeypatch.setattr(cch, "EXCEPTIONS_PATH", exceptions_file)

    out = StringIO()
    call_command("check_chart_health", "--fail-on-findings", stdout=out)  # must not raise
    output = out.getvalue()
    assert tenant.subdomain in output
    assert "ACCEPTED EXCEPTION" in output
    assert "0 findings" in output
