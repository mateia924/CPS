from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def health(request):
    return JsonResponse({"status": "ok"})

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
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
    path("api/platform/", include("apps.platform.urls")),
]
