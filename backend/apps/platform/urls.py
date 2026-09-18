from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    AuditLogViewSet,
    PlanViewSet,
    PlatformLoginView,
    PlatformMeView,
    TenantAdminViewSet,
)

router = DefaultRouter()
router.register("tenants", TenantAdminViewSet, basename="platform-tenant")
router.register("plans", PlanViewSet, basename="platform-plan")
router.register("audit-log", AuditLogViewSet, basename="platform-audit-log")

urlpatterns = [
    path("auth/login/", PlatformLoginView.as_view(), name="platform-login"),
    path("auth/me/", PlatformMeView.as_view(), name="platform-me"),
] + router.urls
