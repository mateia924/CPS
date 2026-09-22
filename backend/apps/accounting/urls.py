from rest_framework.routers import DefaultRouter

from .views import AccountViewSet, JournalEntryViewSet, TaxCodeViewSet, TaxPeriodViewSet

router = DefaultRouter()
router.register("accounts", AccountViewSet, basename="account")
router.register("journal-entries", JournalEntryViewSet, basename="journal-entry")
router.register("tax-codes", TaxCodeViewSet, basename="tax-code")
router.register("tax-periods", TaxPeriodViewSet, basename="tax-period")

urlpatterns = router.urls
