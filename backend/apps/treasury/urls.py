from rest_framework.routers import DefaultRouter

from .views import (
    BankStatementLineViewSet,
    BankStatementViewSet,
    BankViewSet,
    CashBoxViewSet,
    CashCountViewSet,
    CustodyViewSet,
    ExchangeRateViewSet,
    IbanChangeRequestViewSet,
)

router = DefaultRouter()
router.register("banks", BankViewSet, basename="bank")
router.register("cash-boxes", CashBoxViewSet, basename="cashbox")
router.register("custodies", CustodyViewSet, basename="custody")
router.register("exchange-rates", ExchangeRateViewSet, basename="exchange-rate")
router.register("iban-requests", IbanChangeRequestViewSet, basename="iban-change-request")
router.register("bank-statements", BankStatementViewSet, basename="bank-statement")
router.register("statement-lines", BankStatementLineViewSet, basename="statement-line")
router.register("cash-counts", CashCountViewSet, basename="cash-count")

urlpatterns = router.urls
