"""Sprint 6.6.3 (item 1): Django admin (/admin/) is session-authenticated,
never touched by apps.tenants.middleware.RLSTenantMiddleware at all
(that one only runs for /api/* paths) — and inherently cross-tenant by
nature (a developer/owner debugging tool, not a customer-facing flow;
several apps/*/admin.py register ModelAdmins for tenant-scoped models).
There is no single `cps.tenant_id` that would ever be correct for it,
so admin requests route to the "platform" alias (the original,
unrestricted role) entirely, via this router + the thread-local flag
apps.tenants.middleware.AdminDatabaseRoutingMiddleware sets.
"""

import threading

_local = threading.local()


def mark_admin_request():
    _local.in_admin = True


def clear_admin_request():
    _local.in_admin = False


class AdminBypassRouter:
    def db_for_read(self, model, **hints):
        return "platform" if getattr(_local, "in_admin", False) else None

    def db_for_write(self, model, **hints):
        return "platform" if getattr(_local, "in_admin", False) else None
