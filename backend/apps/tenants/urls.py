from django.urls import path

from .views import TenantFeaturesView

urlpatterns = [
    path("tenant-features/", TenantFeaturesView.as_view(), name="tenant-features"),
]
