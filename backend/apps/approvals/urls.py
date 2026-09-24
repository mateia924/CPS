from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import ApprovalRuleViewSet, EmergencyApprovalsView, PendingApprovalsView

router = DefaultRouter()
router.register("approval-rules", ApprovalRuleViewSet, basename="approval-rule")

urlpatterns = [
    path("approvals/pending/", PendingApprovalsView.as_view(), name="approvals-pending"),
    path("approvals/emergency/", EmergencyApprovalsView.as_view(), name="approvals-emergency"),
] + router.urls
