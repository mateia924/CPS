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
    path("api/platform/", include("apps.platform.urls")),
]
