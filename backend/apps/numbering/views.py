from django.utils.translation import gettext_lazy as _
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.access.permissions import HasModulePermission
from apps.common.viewsets import TenantScopedViewSet

from .models import DocumentNumberingSetting
from .serializers import DocumentNumberingSettingSerializer
from .services import (
    DEFAULT_PREFIXES,
    get_or_create_numbering_setting,
    issued_documents_this_year_count,
)


class DocumentNumberingSettingViewSet(TenantScopedViewSet):
    """Settings ← "ترقيم المستندات" (3.18): edit each doc_type's prefix
    (basic) and yearly-reset choice (advanced). No create/delete —
    rows are one-per-doc_type and lazily auto-created (here, for every
    known doc_type, so the screen always lists a complete, predictable
    set; and in services.next_document_number, for any doc_type used
    before an admin ever visits this screen).

    Sprint 6.6.5 (item 4, revised after the real INVX-2026-00005/00002
    incident on tenant Fatma — sprint-4 UAT item 16 deliberately
    changed the invoice prefix mid-year to test exactly this screen,
    and the resulting real, numbered documents were never meant to be
    permanent): changing `prefix` for a doc_type that already has
    numbered documents in the CURRENT calendar year is now a 400,
    same "control-account override" shape as apps.accounting.services.
    create_manual_journal_entry — an explicit `override_reason` in the
    request body lets it through anyway and is logged to AuditLog, so
    a deliberate mid-year test/change is still possible but can never
    happen silently/by accident again."""

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

    def partial_update(self, request, *args, **kwargs):
        from apps.platform.models import AuditLog
        from apps.platform.services import log_action

        setting = self.get_object()
        new_prefix = request.data.get("prefix", setting.prefix)
        if new_prefix != setting.prefix:
            issued_count = issued_documents_this_year_count(request.user.tenant, setting.doc_type)
            if issued_count:
                override_reason = request.data.get("override_reason", "")
                if not override_reason:
                    return Response(
                        {
                            "prefix": [
                                str(
                                    _(
                                        "%(count)s document(s) of this type already carry a number this "
                                        "year under the current prefix — changing it now would split the "
                                        "sequence mid-year. Provide override_reason to proceed anyway."
                                    )
                                    % {"count": issued_count}
                                )
                            ]
                        },
                        status=400,
                    )
                log_action(
                    actor_type=AuditLog.ActorType.TENANT_USER, actor_id=request.user.id,
                    action="numbering_setting.prefix_override", target_type="documentnumberingsetting",
                    target_id=setting.id, tenant_id=request.user.tenant_id,
                    before={"prefix": setting.prefix},
                    after={"prefix": new_prefix, "issued_count": issued_count, "reason": override_reason},
                    request=request,
                )
        return super().partial_update(request, *args, **kwargs)
