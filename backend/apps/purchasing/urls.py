from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import PurchaseSettingsView, WithholdingTaxCodeViewSet

router = DefaultRouter()
router.register("purchasing/withholding-codes", WithholdingTaxCodeViewSet, basename="withholding-code")

urlpatterns = [
    path("purchasing/settings/", PurchaseSettingsView.as_view(), name="purchase-settings"),
    path("", include(router.urls)),
]
