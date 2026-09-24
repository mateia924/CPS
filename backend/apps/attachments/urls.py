from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import AttachmentDownloadView, AttachmentRuleViewSet, AttachmentViewSet

router = DefaultRouter()
router.register("attachments", AttachmentViewSet, basename="attachment")
router.register("attachment-rules", AttachmentRuleViewSet, basename="attachment-rule")

urlpatterns = [
    path("attachments/<uuid:pk>/download/", AttachmentDownloadView.as_view(), name="attachment-download"),
] + router.urls
