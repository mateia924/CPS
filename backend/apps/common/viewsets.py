from django.db.models import ProtectedError
from django.utils.translation import gettext_lazy as _
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response


class TenantScopedViewSet(viewsets.ModelViewSet):
    """A ModelViewSet that is hard-scoped to request.user.tenant.

    The client can never read or write across tenants: the queryset is
    always filtered by the authenticated user's tenant, and `tenant` is
    always injected server-side, never accepted from request data.
    """

    def get_queryset(self):
        return super().get_queryset().filter(tenant=self.request.user.tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.user.tenant)


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
        return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        instance = self.get_object()
        instance.is_active = True
        instance.save(update_fields=["is_active"])
        return Response(self.get_serializer(instance).data)
