from django.utils.translation import gettext_lazy as _

from .models import Permission, Role

# Fixed "<module>.<action>" catalog (3.14 / sprint 1 spec). Seeded once,
# globally, via a data migration — see migrations/0002_seed_permissions.py.
DEFAULT_PERMISSIONS = [
    ("customers.view", _("View customers")),
    ("customers.manage", _("Create, edit and delete customers")),
    ("products.view", _("View products")),
    ("products.manage", _("Create, edit and delete products")),
    ("invoices.view", _("View invoices")),
    ("invoices.create", _("Create invoices")),
    ("invoices.approve", _("Issue/approve invoices")),
    ("accounting.view", _("View the chart of accounts and journal entries")),
    # Sprint 4.3 (3.15.9 control matrix: "تعديل دليل الحسابات: مدير
    # حسابات"): the chart-of-accounts screen's write actions.
    ("accounting.manage", _("Create, edit and deactivate accounts in the chart of accounts")),
    ("organization.view", _("View legal entities")),
    ("organization.manage", _("Create, edit and deactivate legal entities")),
    ("costcenters.view", _("View cost centers")),
    ("costcenters.manage", _("Create, edit and deactivate cost centers")),
    ("roles.manage", _("Manage roles, permissions and user assignments")),
    # Sprint 3 (3.3): parties.* supersedes customers.* as the permission
    # gate for the unified "Party" master-data screen (customers is now
    # just one role/tab within it) — customers.* stays in the catalog,
    # unused going forward, never deleted (no permission is ever
    # deleted from the catalog; see the Decision Log).
    ("parties.view", _("View parties (customers, suppliers, employees, affiliates)")),
    ("parties.manage", _("Create, edit and deactivate parties and their roles")),
    ("treasury.view", _("View banks, cash boxes and custodies")),
    ("treasury.manage", _("Create, edit and deactivate banks, cash boxes and custodies")),
    ("assets.view", _("View fixed assets")),
    ("assets.manage", _("Create, edit and deactivate fixed assets")),
    # Sprint 3.5 (3.3 v1.4): the unified "Parties" screen moved to
    # Settings — "الأطراف (عرض شامل)" — for accounts managers only,
    # separate from the ordinary parties.view/manage granted broadly to
    # the per-role screens (Customers/Suppliers/Employees/Affiliates).
    ("parties.view_all", _("View the unified parties screen (all roles at once)")),
    # Sprint 4.1 (3.4/3.18): document numbering settings (prefix,
    # yearly-reset) — Settings ← "ترقيم المستندات".
    ("numbering.view", _("View document numbering settings")),
    ("numbering.manage", _("Edit document numbering prefixes and yearly reset")),
    # Sprint 4.5 (3.15.1): الإعدادات ← "قواعد الاعتماد" + صندوق الاعتماد.
    # approvals.view also gates seeing the approval inbox counter (3.18).
    ("approvals.view", _("View approval rules and the approval inbox")),
    ("approvals.manage", _("Create, edit and deactivate approval rules")),
    # Sprint 5.1 (3.17): every AttachmentPanel goes through these two —
    # "manage" covers upload/void, there is no separate delete permission
    # since no delete path exists at all (rule 6).
    ("attachments.view", _("View attachments")),
    ("attachments.manage", _("Upload and void attachments")),
    # Sprint 5.3 (3.8): سندات القبض/الصرف/التسوية. Separate "post" from
    # "add" the same way accounting.manage vs approvals.manage split
    # authoring from authority elsewhere — a day-to-day accountant can
    # draft a voucher without necessarily being who posts big ones.
    ("vouchers.view", _("View vouchers")),
    ("vouchers.add", _("Create and edit draft vouchers")),
    ("vouchers.post", _("Submit/post vouchers")),
    ("vouchers.approve", _("Approve or reject vouchers pending approval")),
    ("vouchers.reverse", _("Reverse a posted voucher")),
    # Sprint 5.7 (CFO_REVIEW_1 C2): a control account (party sub-ledger,
    # treasury gl_account, tax/FX/rounding/opening/retained-earnings)
    # rejects a manual JV line unless the poster holds this — kept
    # separate from accounting.manage (chart-of-accounts editing) since
    # the two authorities are unrelated.
    ("accounting.post_control_accounts", _("Override the manual-posting block on a control account")),
    # Sprint 5.5 (block 5.5.0, CFO_REVIEW_1 C10): requesting an IBAN
    # change — approving it is gated by the fixed ApprovalRule
    # (required_role=Owner) instead of a separate permission, since
    # 3.15.9 names the approver role explicitly, not a configurable one.
    ("treasury.request_iban_change", _("Request an IBAN change for a bank or supplier")),
]

# Reasonable, editable defaults per system role — not specified in full
# by docs/SYSTEM_ANALYSIS.md (only Owner/Accountant/Sales/Viewer are
# named, "بصلاحيات افتراضية معقولة وقابلة للتعديل"). Logged in
# docs/SYSTEM_ANALYSIS.md section 11. `None` means every permission.
SYSTEM_ROLES = {
    "Owner": None,
    "Accountant": [
        "customers.view",
        "products.view",
        "invoices.view",
        "invoices.create",
        "invoices.approve",
        "accounting.view",
        "accounting.manage",
        "organization.view",
        "costcenters.view",
        "parties.view",
        "parties.view_all",
        "treasury.view",
        "assets.view",
        "numbering.view",
        "approvals.view",
        "attachments.view",
        "attachments.manage",
        "vouchers.view",
        "vouchers.add",
        "vouchers.post",
        "vouchers.approve",
        "vouchers.reverse",
        "treasury.request_iban_change",
    ],
    "Sales": [
        "customers.view",
        "customers.manage",
        "products.view",
        "invoices.view",
        "invoices.create",
        "parties.view",
        "parties.manage",
        "attachments.view",
        "attachments.manage",
    ],
    "Viewer": [
        "customers.view",
        "products.view",
        "invoices.view",
        "accounting.view",
        "organization.view",
        "costcenters.view",
        "parties.view",
        "treasury.view",
        "assets.view",
        "attachments.view",
        "vouchers.view",
    ],
}


def seed_permissions():
    """Idempotent: ensure the global permission catalog exists. Called
    from a data migration; safe to call again."""
    for code, description in DEFAULT_PERMISSIONS:
        Permission.objects.update_or_create(code=code, defaults={"description": description})


def seed_default_roles(tenant):
    """Create the four system roles for a tenant with their default
    permission sets. Returns {name: Role}. Used at registration and by
    the Sprint 1 data migration for pre-existing tenants."""
    all_codes = [code for code, _description in DEFAULT_PERMISSIONS]
    roles = {}
    for name, codes in SYSTEM_ROLES.items():
        role = Role.objects.create(tenant=tenant, name=name, is_system=True)
        role.permissions.set(Permission.objects.filter(code__in=(codes or all_codes)))
        roles[name] = role
    return roles


def user_has_permission(user, code):
    return Role.objects.filter(users=user, permissions__code=code).exists()


def user_is_owner(user):
    return Role.objects.filter(
        users=user, tenant_id=user.tenant_id, name="Owner", is_system=True
    ).exists()


def active_owner_count(tenant, exclude_user_id=None):
    """docs/SYSTEM_ANALYSIS.md section 4 rule 9 / sprint 1.5 rule 3: a
    tenant must always keep at least one active Owner. Used to block
    both deactivating the last one and stripping their Owner role."""
    from apps.accounts.models import User

    qs = User.objects.filter(
        tenant=tenant, is_active=True, roles__name="Owner", roles__is_system=True
    )
    if exclude_user_id is not None:
        qs = qs.exclude(id=exclude_user_id)
    return qs.distinct().count()
