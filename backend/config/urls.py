from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.accounting.views import DashboardSummaryView
from apps.platform.views import TenantAuditLogViewSet


def health(request):
    return JsonResponse({"status": "ok"})


# Sprint 5.7 (CFO_REVIEW_1 F10): "سجل التغييرات" — a tenant user's own
# read-only AuditLog window, separate from apps.platform's own
# (cross-tenant, staff-only) audit-log endpoint under /api/platform/.
_tenant_router = DefaultRouter()
_tenant_router.register("audit-log", TenantAuditLogViewSet, basename="tenant-audit-log")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    path("api/dashboard/summary/", DashboardSummaryView.as_view(), name="dashboard-summary"),
    path("api/", include(_tenant_router.urls)),
    path("api/auth/", include("apps.accounts.urls")),
    path("api/", include("apps.sales.urls")),
    path("api/", include("apps.accounting.urls")),
    path("api/", include("apps.organization.urls")),
    path("api/", include("apps.access.urls")),
    path("api/", include("apps.numbering.urls")),
    path("api/", include("apps.approvals.urls")),
    path("api/", include("apps.parties.urls")),
    path("api/", include("apps.treasury.urls")),
    path("api/", include("apps.assets.urls")),
    path("api/", include("apps.attachments.urls")),
    path("api/", include("apps.vouchers.urls")),
    path("api/", include("apps.reports.urls")),
    path("api/", include("apps.inventory.urls")),
    path("api/", include("apps.tenants.urls")),
    path("api/platform/", include("apps.platform.urls")),
]
