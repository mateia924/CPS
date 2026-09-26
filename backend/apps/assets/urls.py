from rest_framework.routers import DefaultRouter

from .views import AssetViewSet, DepreciationScheduleViewSet

router = DefaultRouter()
router.register("assets", AssetViewSet, basename="asset")
router.register("depreciation-schedules", DepreciationScheduleViewSet, basename="depreciation-schedule")

urlpatterns = router.urls
