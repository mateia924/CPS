from rest_framework.routers import DefaultRouter

from .views import AccountViewSet, JournalEntryViewSet

router = DefaultRouter()
router.register("accounts", AccountViewSet, basename="account")
router.register("journal-entries", JournalEntryViewSet, basename="journal-entry")

urlpatterns = router.urls
