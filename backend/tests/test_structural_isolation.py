"""Architectural review #1 (2026-09-22, docs/ARCH_REVIEW_1.md section 2):
a structural, introspection-based guard against the exact class of bug
found (and fixed) in PartyViewSet during sprint 3 — a ViewSet that
declared `permission_map` but never put `HasModulePermission` in its
`permission_classes`, so the map was silently dead and any authenticated
user of any role could manage parties. Tenant isolation itself was NOT
broken (PartyViewSet correctly inherited TenantScopedViewSet) — only
RBAC enforcement was.

This walks every view actually registered in urlpatterns via Django's
own URL resolver, not a hand-maintained list — a new ViewSet added in a
future sprint is automatically picked up and must be explicitly
classified below (tenant-scoped, a documented exemption, or genuinely
not tenant data) or these tests fail with its name in the message.
"""

from django.urls import get_resolver

from apps.access.permissions import HasModulePermission
from apps.common.viewsets import TenantScopedViewSet

# ViewSets that correctly do NOT inherit TenantScopedViewSet but still
# scope every queryset to request.user.tenant by hand — verified by
# reading get_queryset() on each (see docs/ARCH_REVIEW_1.md section 2).
# Every entry needs a real reason; this dict is reviewed by a human each
# time a class is added to it.
TENANT_FILTER_EXEMPTIONS = {
    "apps.access.views.PermissionViewSet": "global permission catalog, no tenant field on Permission",
    "apps.access.views.UserViewSet": "get_queryset() filters User.objects.filter(tenant=request.user.tenant) by hand",
    "apps.accounting.views.AccountViewSet": "get_queryset() filters Account.objects.filter(tenant=request.user.tenant) by hand",
    "apps.accounting.views.JournalEntryViewSet": "get_queryset() filters by tenant + get_accessible_entity_ids() by hand",
    "apps.sales.views.InvoiceViewSet": "get_queryset() filters by tenant + get_accessible_entity_ids() by hand",
    "apps.approvals.views.PendingApprovalsView": "plain APIView aggregating two already-tenant-scoped queries (JournalEntry/Invoice, both explicitly filtered by request.user.tenant) — not a ModelViewSet, so TenantScopedViewSet inheritance doesn't apply structurally",
    "apps.accounting.views.TaxPeriodViewSet": "get_queryset() filters by tenant + get_accessible_entity_ids() by hand, same pattern as JournalEntryViewSet above",
    "apps.attachments.views.AttachmentViewSet": "get_queryset() filters Attachment.objects.filter(tenant=request.user.tenant) by hand; create() resolves its GenericFK target only within request.user.tenant (services.resolve_target) — a cross-tenant target_id 404s, never 403",
    "apps.attachments.views.AttachmentDownloadView": "deliberately AllowAny (no bearer token at all — a plain <a href> or mobile camera flow can't carry Authorization) — isolation is enforced by the HMAC-signed link itself (services.verify_link), not a request.user.tenant filter: forging a valid token for another tenant's attachment id is cryptographically infeasible without ATTACHMENT_LINK_SIGNING_KEY",
    "apps.vouchers.views.VoucherViewSet": "get_queryset() filters by tenant + get_accessible_entity_ids() by hand, same pattern as JournalEntryViewSet",
    "apps.treasury.views.IbanChangeRequestViewSet": "get_queryset() filters IbanChangeRequest.objects.filter(tenant=request.user.tenant) by hand, same pattern as VoucherViewSet (sprint 5.5 block 5.5.0)",
    "apps.treasury.views.BankStatementViewSet": "get_queryset() filters BankStatement.objects.filter(tenant=request.user.tenant) by hand, same pattern as VoucherViewSet (sprint 5.5 block 5.5.1)",
    "apps.treasury.views.BankStatementLineViewSet": "get_queryset() filters BankStatementLine.objects.filter(tenant=request.user.tenant) by hand, same pattern as VoucherViewSet (sprint 5.5 block 5.5.2)",
    "apps.platform.views.TenantAuditLogViewSet": "AuditLog is not a TenantScopedModel (a plain tenant_id UUID, not a FK — shared with the platform-side AuditLogViewSet) — get_queryset() filters AuditLog.objects.filter(tenant_id=request.user.tenant_id) by hand",
}

# Views that are correctly not tenant-scoped at all: public auth entry
# points (no authenticated tenant context yet) or platform-side views
# that are intentionally cross-tenant (a platform admin's whole job is
# seeing every tenant — see docs/SYSTEM_ANALYSIS.md 3.14).
NOT_TENANT_DATA = {
    "apps.accounts.views.RegisterView",
    "apps.accounts.views.LoginView",
    "apps.accounts.views.MeView",
    "rest_framework_simplejwt.views.TokenRefreshView",
    "apps.platform.views.PlatformLoginView",
    "apps.platform.views.PlatformMeView",
    "apps.platform.views.TenantAdminViewSet",
    "apps.platform.views.PlanViewSet",
    "apps.platform.views.AuditLogViewSet",
    "rest_framework.routers.APIRootView",
}


def _qualified_name(cls):
    return f"{cls.__module__}.{cls.__name__}"


def _registered_view_classes():
    """Every distinct view class backing a registered URL, found via
    Django's own resolver rather than a hand-maintained list of apps."""

    def walk(patterns):
        classes = []
        for pattern in patterns:
            if hasattr(pattern, "url_patterns"):
                classes.extend(walk(pattern.url_patterns))
            else:
                cls = getattr(pattern.callback, "cls", None)
                if cls is not None:
                    classes.append(cls)
        return classes

    seen = {}
    for cls in walk(get_resolver().url_patterns):
        seen[_qualified_name(cls)] = cls
    return seen


def test_every_registered_view_is_classified():
    """Anti-recurrence check: a brand-new ViewSet must be explicitly
    sorted into "tenant-scoped", an exemption with a reason, or
    "not tenant data" — never silently left unclassified. This test
    exists so the two checks below can trust their own exemption lists;
    without it, a new class could slip past both simply by not being on
    either list, since the loops below only assert about classes they
    already expect to see less of."""
    classes = _registered_view_classes()
    unclassified = [
        name
        for name, cls in classes.items()
        if name not in TENANT_FILTER_EXEMPTIONS
        and name not in NOT_TENANT_DATA
        and not issubclass(cls, TenantScopedViewSet)
    ]
    assert not unclassified, (
        "New view(s) not classified as tenant-scoped, an exemption, or "
        "non-tenant data — add each to TenantScopedViewSet, "
        "TENANT_FILTER_EXEMPTIONS (with a reason), or NOT_TENANT_DATA in "
        f"tests/test_structural_isolation.py: {unclassified}"
    )


def test_every_tenant_scoped_view_enables_has_module_permission_when_mapped():
    """The exact PartyViewSet bug: a view that declares `permission_map`
    (meaning RBAC enforcement was clearly intended) but omits
    HasModulePermission from permission_classes, so the map is dead code
    and HasModulePermission.has_permission() is never even called for
    that view — any authenticated user passes, regardless of role."""
    classes = _registered_view_classes()
    broken = []
    for name, cls in classes.items():
        permission_map = getattr(cls, "permission_map", None)
        if not permission_map:
            continue
        permission_classes = getattr(cls, "permission_classes", None) or []
        if HasModulePermission not in permission_classes:
            broken.append(name)
    assert not broken, (
        "View(s) declare permission_map but never put HasModulePermission "
        f"in permission_classes, so the map is never enforced: {broken}"
    )


def test_every_tenant_data_view_is_tenant_scoped_or_exempted_with_a_reason():
    """Every view reachable at a URL that touches tenant-owned data must
    inherit TenantScopedViewSet (get_queryset() filtered by
    request.user.tenant automatically) or be in TENANT_FILTER_EXEMPTIONS
    with a documented reason it's still safe. A view legitimately outside
    tenant data at all belongs in NOT_TENANT_DATA instead."""
    classes = _registered_view_classes()
    for name in TENANT_FILTER_EXEMPTIONS:
        assert name in classes, (
            f"{name} is listed in TENANT_FILTER_EXEMPTIONS but no longer "
            "exists as a registered view — remove the stale entry."
        )
    for name in NOT_TENANT_DATA:
        assert name in classes, (
            f"{name} is listed in NOT_TENANT_DATA but no longer exists as "
            "a registered view — remove the stale entry."
        )

    violations = [
        name
        for name, cls in classes.items()
        if name not in TENANT_FILTER_EXEMPTIONS
        and name not in NOT_TENANT_DATA
        and not issubclass(cls, TenantScopedViewSet)
    ]
    assert not violations, (
        f"View(s) are not tenant-scoped and not exempted: {violations}"
    )
