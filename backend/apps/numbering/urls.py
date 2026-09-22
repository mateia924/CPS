from rest_framework.routers import DefaultRouter

from .views import DocumentNumberingSettingViewSet

router = DefaultRouter()
router.register("document-numbering-settings", DocumentNumberingSettingViewSet, basename="numbering-setting")

urlpatterns = router.urls
