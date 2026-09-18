from rest_framework.routers import DefaultRouter

from .views import CostCenterViewSet, LegalEntityViewSet

router = DefaultRouter()
router.register("legal-entities", LegalEntityViewSet, basename="legal-entity")
router.register("cost-centers", CostCenterViewSet, basename="cost-center")

urlpatterns = router.urls
