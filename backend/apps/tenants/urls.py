from django.urls import path

from .views import TenantFeaturesView, TenantSettingsView

urlpatterns = [
    path("tenant-features/", TenantFeaturesView.as_view(), name="tenant-features"),
    path("tenant-settings/", TenantSettingsView.as_view(), name="tenant-settings"),
]
