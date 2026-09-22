from rest_framework.permissions import IsAuthenticated

from apps.access.permissions import HasModulePermission
from apps.common.viewsets import TenantScopedViewSet

from .models import DocumentNumberingSetting
from .serializers import DocumentNumberingSettingSerializer
from .services import DEFAULT_PREFIXES, get_or_create_numbering_setting


class DocumentNumberingSettingViewSet(TenantScopedViewSet):
    """Settings ← "ترقيم المستندات" (3.18): edit each doc_type's prefix
    (basic) and yearly-reset choice (advanced). No create/delete —
    rows are one-per-doc_type and lazily auto-created (here, for every
    known doc_type, so the screen always lists a complete, predictable
    set; and in services.next_document_number, for any doc_type used
    before an admin ever visits this screen)."""

    http_method_names = ["get", "patch", "head", "options"]
    permission_classes = [IsAuthenticated, HasModulePermission]
    serializer_class = DocumentNumberingSettingSerializer
    queryset = DocumentNumberingSetting.objects.all()
    permission_map = {
        "list": "numbering.view",
        "retrieve": "numbering.view",
        "partial_update": "numbering.manage",
    }

    def get_queryset(self):
        if self.action == "list":
            for doc_type in DEFAULT_PREFIXES:
                get_or_create_numbering_setting(self.request.user.tenant, doc_type)
        return super().get_queryset().order_by("doc_type")
