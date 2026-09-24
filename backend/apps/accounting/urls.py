from rest_framework.routers import DefaultRouter

from .views import (
    AccountViewSet,
    FiscalPeriodViewSet,
    FiscalYearViewSet,
    JournalEntryViewSet,
    OpeningBalanceViewSet,
    RecurringEntryViewSet,
    RecurringInstallmentViewSet,
    TaxCodeViewSet,
    TaxPeriodViewSet,
)

router = DefaultRouter()
router.register("accounts", AccountViewSet, basename="account")
router.register("journal-entries", JournalEntryViewSet, basename="journal-entry")
router.register("tax-codes", TaxCodeViewSet, basename="tax-code")
router.register("tax-periods", TaxPeriodViewSet, basename="tax-period")
router.register("fiscal-years", FiscalYearViewSet, basename="fiscal-year")
router.register("fiscal-periods", FiscalPeriodViewSet, basename="fiscal-period")
router.register("opening-balances", OpeningBalanceViewSet, basename="opening-balance")
router.register("recurring-entries", RecurringEntryViewSet, basename="recurring-entry")
router.register("recurring-installments", RecurringInstallmentViewSet, basename="recurring-installment")

urlpatterns = router.urls
