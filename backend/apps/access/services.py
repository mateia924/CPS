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
    ("organization.view", _("View legal entities")),
    ("organization.manage", _("Create, edit and deactivate legal entities")),
    ("costcenters.view", _("View cost centers")),
    ("costcenters.manage", _("Create, edit and deactivate cost centers")),
    ("roles.manage", _("Manage roles, permissions and user assignments")),
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
        "organization.view",
        "costcenters.view",
    ],
    "Sales": [
        "customers.view",
        "customers.manage",
        "products.view",
        "invoices.view",
        "invoices.create",
    ],
    "Viewer": [
        "customers.view",
        "products.view",
        "invoices.view",
        "accounting.view",
        "organization.view",
        "costcenters.view",
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
