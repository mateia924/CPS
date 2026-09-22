from rest_framework.routers import DefaultRouter

from .views import BankViewSet, CashBoxViewSet, CustodyViewSet, ExchangeRateViewSet

router = DefaultRouter()
router.register("banks", BankViewSet, basename="bank")
router.register("cash-boxes", CashBoxViewSet, basename="cashbox")
router.register("custodies", CustodyViewSet, basename="custody")
router.register("exchange-rates", ExchangeRateViewSet, basename="exchange-rate")

urlpatterns = router.urls
