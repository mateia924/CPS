from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ExpensesView,
    PayablesByWeekView,
    PurchaseSettingsView,
    SupplierBillViewSet,
    WithholdingTaxCodeViewSet,
)

router = DefaultRouter()
router.register("purchasing/withholding-codes", WithholdingTaxCodeViewSet, basename="withholding-code")
router.register("purchasing/bills", SupplierBillViewSet, basename="supplier-bill")

urlpatterns = [
    path("purchasing/settings/", PurchaseSettingsView.as_view(), name="purchase-settings"),
    path("purchasing/expenses/", ExpensesView.as_view(), name="purchase-expenses"),
    path("purchasing/payables-by-week/", PayablesByWeekView.as_view(), name="purchase-payables-by-week"),
    path("", include(router.urls)),
]
