from rest_framework.routers import DefaultRouter

from .views import AssetDisposalViewSet, AssetViewSet, DepreciationScheduleViewSet

router = DefaultRouter()
router.register("assets", AssetViewSet, basename="asset")
router.register("depreciation-schedules", DepreciationScheduleViewSet, basename="depreciation-schedule")
router.register("asset-disposals", AssetDisposalViewSet, basename="asset-disposal")

urlpatterns = router.urls
