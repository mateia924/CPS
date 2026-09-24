from django.db.models import ProtectedError
from django.utils.translation import gettext_lazy as _
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response


def model_field_snapshot(instance):
    """Sprint 6.8 (F10, decision 21): a JSON-safe {field_name: value}
    snapshot of every concrete column on `instance` (skipping id/
    tenant/timestamps — never useful in a diff), used to build the
    before/after this app's `log_action` calls always want. FKs are
    captured by their raw id (`field.attname`), never a second query
    to render a display value — good enough for a change-history list,
    and avoids N+1s on every single write in the app."""
    import datetime
    import uuid as uuid_module
    from decimal import Decimal

    data = {}
    for field in instance._meta.concrete_fields:
        if field.name in ("id", "tenant", "created_at", "updated_at"):
            continue
        value = getattr(instance, field.attname)
        if isinstance(value, Decimal):
            value = str(value)
        elif isinstance(value, (datetime.date, datetime.datetime)):
            value = value.isoformat()
        elif isinstance(value, uuid_module.UUID):
            value = str(value)
        data[field.name] = value
    return data


def log_master_data_change(request, instance, action_suffix, before=None, after=None):
    """Sprint 6.8 (F10, decision 21): `log_action` on create/edit/
    deactivate for master data — Party (every role screen), Bank,
    CashBox, Custody, Asset, Account, TaxCode, ExchangeRate,
    ApprovalRule, AttachmentRule, DocumentNumberingSetting, LegalEntity.
    Called from the two shared base classes below so every model using
    them gets this uniformly, with no per-model copy of the call."""
    from apps.platform.models import AuditLog
    from apps.platform.services import log_action

    model = type(instance)
    target_type = f"{model._meta.app_label}.{model._meta.model_name}"
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER, actor_id=request.user.id,
        action=f"{target_type}.{action_suffix}", target_type=target_type, target_id=instance.pk,
        tenant_id=request.user.tenant_id, before=before, after=after, request=request,
    )


class TenantScopedViewSet(viewsets.ModelViewSet):
    """A ModelViewSet that is hard-scoped to request.user.tenant.

    The client can never read or write across tenants: the queryset is
    always filtered by the authenticated user's tenant, and `tenant` is
    always injected server-side, never accepted from request data.
    """

    def get_queryset(self):
        return super().get_queryset().filter(tenant=self.request.user.tenant)

    def perform_create(self, serializer):
        instance = serializer.save(tenant=self.request.user.tenant)
        log_master_data_change(self.request, instance, "created", after=model_field_snapshot(instance))

    def perform_update(self, serializer):
        before = model_field_snapshot(serializer.instance)
        instance = serializer.save()
        after = model_field_snapshot(instance)
        changed_before = {k: v for k, v in before.items() if after.get(k) != v}
        changed_after = {k: v for k, v in after.items() if before.get(k) != v}
        if changed_after:
            log_master_data_change(self.request, instance, "updated", before=changed_before, after=changed_after)


class SoftDeleteViewSetMixin:
    """docs/SYSTEM_ANALYSIS.md section 4 rule 9 / sprint 1.5 rule 3: "an
    entity with transactions is only ever deactivated, never actually
    deleted; an actual-delete attempt returns 409".

    - DELETE attempts a real delete. Every relationship that should
      block it is already `on_delete=PROTECT` at the model level
      (Invoice.party, InvoiceLine.product, LegalEntity/CostCenter's
      self-FK parent, etc.) — this mixin's only job is turning the
      resulting ProtectedError into a clean 409 instead of a 500. An
      entity with zero references really is deleted.
    - `deactivate`/`activate` toggle `is_active` directly and always
      succeed regardless of references — this is the primary, safe
      action the UI's "تعطيل/إعادة تفعيل" buttons call.
    - `list` hides inactive rows unless `?show_inactive=true` is passed;
      `retrieve`/`deactivate`/`activate`/etc. are never filtered by
      is_active, since you must be able to fetch and reactivate an
      inactive record by id.

    Requires the model to have an `is_active` BooleanField.
    """

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == "list" and self.request.query_params.get("show_inactive") != "true":
            queryset = queryset.filter(is_active=True)
        return queryset

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {
                    "detail": _(
                        "This record is referenced elsewhere and cannot be deleted. Deactivate it instead."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        instance = self.get_object()
        instance.is_active = False
        instance.save(update_fields=["is_active"])
        log_master_data_change(request, instance, "deactivated")
        return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        instance = self.get_object()
        instance.is_active = True
        instance.save(update_fields=["is_active"])
        log_master_data_change(request, instance, "activated")
        return Response(self.get_serializer(instance).data)
