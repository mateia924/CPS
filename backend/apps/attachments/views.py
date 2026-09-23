from django.conf import settings
from django.db import models, transaction
from django.http import FileResponse
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access.permissions import HasModulePermission
from apps.platform.models import AuditLog
from apps.platform.services import log_action

from .models import Attachment
from .serializers import AttachmentSerializer, AttachmentUploadSerializer, VoidAttachmentSerializer
from .services import (
    ALLOWED_TARGETS,
    AttachmentValidationError,
    LinkInvalid,
    StorageQuotaExceeded,
    check_file_size,
    check_storage_limit,
    compute_sha256,
    detect_mime_type,
    resolve_target,
    sign_link,
    verify_link,
)
from .tasks import scan_attachment

# Master-data/settings targets get versioned (a same-category re-upload
# supersedes the previous one); financial documents never do — a second
# receipt on an invoice is an ADDITION, not a replacement (3.17 table).
VERSIONED_TARGETS = {"party", "bank", "cash_box", "custody", "asset", "account", "tax_code", "exchange_rate"}


class AttachmentViewSet(
    mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """docs/SYSTEM_ANALYSIS.md 3.17 — backs AttachmentPanel (5.2). No
    PUT/PATCH/DELETE at all (rule 6: nothing is ever hard-deleted); the
    only ways to change a row after upload are `void` (any attachment,
    with a reason) and uploading a new version (versioned targets only,
    handled entirely inside `create`)."""

    serializer_class = AttachmentSerializer
    permission_classes = [IsAuthenticated, HasModulePermission]
    http_method_names = ["get", "post", "head", "options"]
    permission_map = {
        "list": "attachments.view",
        "retrieve": "attachments.view",
        "create": "attachments.manage",
        "link": "attachments.view",
        "void": "attachments.manage",
    }

    def get_queryset(self):
        queryset = Attachment.objects.filter(tenant=self.request.user.tenant).select_related(
            "uploaded_by", "voided_by", "content_type"
        )
        target_type = self.request.query_params.get("target_type")
        target_id = self.request.query_params.get("target_id")
        if target_type and target_id:
            mapping = ALLOWED_TARGETS.get(target_type)
            if mapping is None:
                return queryset.none()
            app_label, model_name = mapping
            queryset = queryset.filter(
                content_type__app_label=app_label, content_type__model=model_name, object_id=target_id
            )
        # Active first, then voided/superseded — the panel folds the
        # rest under "older versions" (5.2), it doesn't hide them.
        return queryset.order_by("-status", "-version", "-uploaded_at")

    def create(self, request, *args, **kwargs):
        serializer = AttachmentUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        tenant = request.user.tenant

        try:
            content_type, target = resolve_target(tenant, data["target_type"], data["target_id"])
        except AttachmentValidationError as exc:
            if "target_id" in exc.message_dict:
                return Response(exc.message_dict, status=404)
            return Response(exc.message_dict, status=400)

        file_obj = data["file"]
        try:
            check_file_size(tenant, file_obj.size)
            check_storage_limit(tenant, file_obj.size)
        except StorageQuotaExceeded as exc:
            return Response({"detail": str(exc.message)}, status=413)

        try:
            mime_type = detect_mime_type(file_obj, file_obj.name)
        except AttachmentValidationError as exc:
            return Response(exc.message_dict, status=400)

        sha256 = compute_sha256(file_obj)

        version, supersedes = 1, None
        if data["target_type"] in VERSIONED_TARGETS:
            previous = (
                Attachment.objects.filter(
                    tenant=tenant, content_type=content_type, object_id=target.id,
                    category=data["category"], status=Attachment.Status.ACTIVE,
                )
                .order_by("-version")
                .first()
            )
            if previous is not None:
                version, supersedes = previous.version + 1, previous

        with transaction.atomic():
            attachment = Attachment.objects.create(
                tenant=tenant,
                content_type=content_type,
                object_id=target.id,
                file=file_obj,
                original_name=file_obj.name,
                mime_type=mime_type,
                size=file_obj.size,
                sha256=sha256,
                category=data["category"],
                description=data.get("description", ""),
                uploaded_by=request.user,
                upload_ip=request.META.get("REMOTE_ADDR"),
                version=version,
                supersedes=supersedes,
            )
            tenant.__class__.objects.filter(id=tenant.id).update(
                storage_used_bytes=models.F("storage_used_bytes") + file_obj.size
            )

        scan_attachment.delay(str(attachment.id))
        # In real (non-eager) use this is a no-op — the async task hasn't
        # run yet, so scan_status is still legitimately "pending" in the
        # response. Under CELERY_TASK_ALWAYS_EAGER (tests), the task above
        # already ran synchronously and updated the DB through its OWN
        # fresh `Attachment.objects.get(...)` instance — without this
        # refresh, the response would serialize this view's original,
        # now-stale in-memory `attachment` object instead.
        attachment.refresh_from_db()

        log_action(
            actor_type=AuditLog.ActorType.TENANT_USER,
            actor_id=request.user.id,
            action="attachment.upload",
            target_type="attachment",
            target_id=attachment.id,
            tenant_id=tenant.id,
            after={
                "original_name": attachment.original_name, "sha256": attachment.sha256,
                "category": attachment.category, "target_type": data["target_type"],
            },
            request=request,
        )
        return Response(AttachmentSerializer(attachment).data, status=201)

    @action(detail=True, methods=["post"])
    def link(self, request, pk=None):
        attachment = self.get_object()
        token = sign_link(attachment.id, requested_by_id=request.user.id)
        return Response({"token": token, "expires_in": settings.ATTACHMENT_LINK_TTL_SECONDS})

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        attachment = self.get_object()
        serializer = VoidAttachmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        attachment.status = Attachment.Status.VOIDED
        attachment.void_reason = serializer.validated_data["reason"]
        attachment.voided_by = request.user
        attachment.voided_at = timezone.now()
        attachment.save(update_fields=["status", "void_reason", "voided_by", "voided_at"])
        log_action(
            actor_type=AuditLog.ActorType.TENANT_USER,
            actor_id=request.user.id,
            action="attachment.void",
            target_type="attachment",
            target_id=attachment.id,
            tenant_id=request.user.tenant_id,
            after={"reason": attachment.void_reason},
            request=request,
        )
        return Response(AttachmentSerializer(attachment).data)


class AttachmentDownloadView(APIView):
    """`GET /api/attachments/{id}/download/?token=...` — deliberately
    unauthenticated (AllowAny): a signed link is meant to work from a
    plain <a href> or a browser tab with no Authorization header (the
    mobile-camera upload/download flow, 3.17). Isolation is enforced by
    the signature itself (services.verify_link — forging a token for
    another tenant's attachment id is infeasible without the signing
    key), not by a bearer token on this specific request."""

    permission_classes = [AllowAny]

    def get(self, request, pk):
        token = request.query_params.get("token", "")
        try:
            requested_by = verify_link(token, pk)
        except LinkInvalid:
            return Response({"detail": "الرابط منتهي الصلاحية أو غير صالح."}, status=403)

        try:
            attachment = Attachment.objects.select_related("tenant").get(id=pk)
        except Attachment.DoesNotExist:
            return Response({"detail": "غير موجود."}, status=404)

        if attachment.scan_status == Attachment.ScanStatus.PENDING:
            return Response({"detail": "الملف قيد الفحص."}, status=409)
        if attachment.scan_status not in (Attachment.ScanStatus.CLEAN, Attachment.ScanStatus.SKIPPED):
            return Response({"detail": "الملف مرفوض."}, status=409)

        log_action(
            actor_type=AuditLog.ActorType.TENANT_USER,
            actor_id=requested_by,
            action="attachment.download",
            target_type="attachment",
            target_id=attachment.id,
            tenant_id=attachment.tenant_id,
            request=request,
        )

        disposition = (
            "inline" if attachment.mime_type in ("application/pdf",) or attachment.mime_type.startswith("image/")
            else "attachment"
        )
        response = FileResponse(attachment.file.open("rb"), content_type=attachment.mime_type)
        response["Content-Disposition"] = f'{disposition}; filename="{attachment.original_name}"'
        return response
