from django.db.models import ProtectedError
from django.db.models.deletion import Collector
from django.utils import timezone
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


class EntityScopedMixin:
    """Sprint 6.6.1 (closes the four gaps audited in 6.5.13 — Asset/
    Bank/CashBox/Custody had NO entity-scoping at all — plus every
    other ViewSet whose model reaches a legal entity, one shared place
    instead of each repeating/forgetting the same two lines): scopes
    every action's queryset (list, retrieve, and any custom `@action`
    that calls `self.get_object()`, since DRF's own `get_object()`
    always filters through `get_queryset()` — no per-action code
    needed) to the entities `request.user` can access
    (`apps.organization.services.get_accessible_entity_ids`) — an
    Owner sees every entity in the tenant; an entity-restricted user
    only their own entity and its descendants.

    A plain mixin (no base class of its own) so it combines with
    whatever queryset chain a ViewSet already has — `EntityScopedViewSet`
    below for the common case (full `TenantScopedViewSet`, no other
    `get_queryset()` override needed at all: this mixin's own
    `get_queryset()` calls `super().get_queryset()` and filters on top
    of it). A narrower ViewSet that needs its OWN `get_queryset()`
    anyway (extra filtering by `kind=...`, tenant applied at request
    time, ...) should still inherit this mixin and call
    `super().get_queryset()` as the FIRST thing its own override does,
    same as every other cooperating override in this codebase — a
    `queryset = Model.objects.filter(...)` class attribute (never
    tenant-filtered there; tenant is request-scoped) is the normal way
    to give that `super()` call something to start from. The one
    escape hatch, `self.scope_to_accessible_entities(queryset)`, is for
    the rare case a subclass's own base queryset genuinely can't be
    expressed that way (a union, raw SQL, ...) — calling it instead of
    `super()` works exactly the same, just skips the rest of the MRO
    chain above this mixin.

    `entity_lookup` (a Django ORM lookup path, "__"-joined) declares
    how to reach the legal entity id from this model — "legal_entity_id"
    by default (a direct FK on the model itself, the common case);
    override it for an indirect relation (e.g. "asset__legal_entity_id"
    for `AssetDisposal`, which has no `legal_entity` field of its own)
    or, for `LegalEntity` itself, "id" (the row being reached IS the
    entity, not a document pointing at one).

    A 404 on `get_object()` — DRF's own behavior for anything filtered
    out of the queryset — is the ONLY way a scope violation ever
    surfaces to the client here, never a 403: matches every other
    scope violation in this codebase ("a scope violation looks like it
    doesn't exist"), and is exactly what replaces the one-off manual
    `if ... not in get_accessible_entity_ids(...): raise Http404` checks
    sprint 6.5.12 added ad hoc in a couple of places (`AssetViewSet.
    generate_due_now`, `DepreciationScheduleViewSet.get_queryset`) —
    removed in this same sprint in favor of inheriting this mixin."""

    entity_lookup = "legal_entity_id"

    def get_queryset(self):
        return self.scope_to_accessible_entities(super().get_queryset())

    def scope_to_accessible_entities(self, queryset):
        from apps.organization.services import get_accessible_entity_ids

        accessible_ids = get_accessible_entity_ids(self.request.user)
        return queryset.filter(**{f"{self.entity_lookup}__in": accessible_ids})


class EntityScopedViewSet(EntityScopedMixin, TenantScopedViewSet):
    """Drop-in replacement for `TenantScopedViewSet` — full CRUD
    (`ModelViewSet`) plus tenant *and* entity scoping. The common case
    (plain master-data/document ViewSets: `AssetViewSet`, `BankViewSet`,
    `CashBoxViewSet`, `CustodyViewSet`, ...). For a narrower ViewSet
    that doesn't want full `ModelViewSet`, use `EntityScopedMixin`
    directly instead (see its own docstring)."""


class SoftDeleteViewSetMixin:
    """docs/SYSTEM_ANALYSIS.md section 4 rule 9 / sprint 1.5 rule 3: "an
    entity with transactions is only ever deactivated, never actually
    deleted; an actual-delete attempt returns 409".

    Sprint 6.6.5 (owner decision 29 Sept, unified delete rule — "لا
    DELETE فعلي في أي مكان"): `destroy` no longer issues a real SQL
    DELETE at all, not even for an entity with zero references. It
    reuses Django's own deletion `Collector` to run the EXACT SAME
    "would anything PROTECT-block this?" walk a real `.delete()` would
    do — `collector.collect([instance])` raises `ProtectedError`
    immediately on the first blocking relation it finds, with no
    actual mutation performed either way — then either 409s (real
    movements exist; the UI's own button would have shown "تعطيل"
    instead of "حذف" for this exact row) or soft-deletes (`deleted_at`/
    `deleted_by`, apps.common.models.SoftDeleteModelMixin — the model
    MUST have these two fields now). Requires the model to have both
    `is_active` (deactivate/activate, unchanged) and `deleted_at`.

    - `list` hides inactive rows unless `?show_inactive=true` is passed,
      and ALWAYS hides soft-deleted ones regardless (no equivalent
      "show deleted" escape hatch — a deleted row is gone from the API
      surface entirely, same as every document's own soft delete).
    - `deactivate`/`activate` toggle `is_active` directly and always
      succeed regardless of references — this is the primary, safe
      action the UI's "تعطيل/إعادة تفعيل" buttons call.
    - `retrieve`/`deactivate`/`activate`/etc. are never filtered by
      is_active, since you must be able to fetch and reactivate an
      inactive record by id — but ARE filtered by deleted_at, since a
      deleted record has no reactivation path at all (unlike
      deactivate, deletion is the project's only genuinely one-way
      door on master data, matching a posted document's own "no
      delete, ever" rule in spirit).
    """

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == "list" and self.request.query_params.get("show_inactive") != "true":
            queryset = queryset.filter(is_active=True)
        return queryset.filter(deleted_at__isnull=True)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        collector = Collector(using=instance._state.db)
        try:
            collector.collect([instance])
        except ProtectedError:
            return Response(
                {
                    "detail": _(
                        "This record is referenced elsewhere and cannot be deleted. Deactivate it instead."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )
        instance.deleted_at = timezone.now()
        instance.deleted_by = request.user
        instance.save(update_fields=["deleted_at", "deleted_by"])
        log_master_data_change(request, instance, "deleted")
        return Response(status=status.HTTP_204_NO_CONTENT)

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


class SoftDeleteDocumentViewSetMixin:
    """Sprint 6.6.5 (owner decision 29 Sept, unified delete rule), the
    document half — generalizes the exact pattern `apps.accounting.
    opening_balances.delete_opening_balance_entry` built for
    OpeningBalanceEntry in sprint 6.6.3d to every other document type:
    a draft/rejected/cancelled document (no posted ledger movement at
    all) gets a real "حذف" button; the model MUST have `deleted_at`/
    `deleted_by` (apps.common.models.SoftDeleteModelMixin) and a
    `status` field. Never a real SQL DELETE ("لا DELETE فعلي في أي
    مكان") — a posted/approved/pending-approval document stays 409,
    no exceptions, no override point for that part.

    `deletable_statuses` names which `instance.status` values are
    eligible — override per model. The one default here (`"draft"`)
    covers every `apps.common.models.DocumentStateMixin`-based
    document (JournalEntry, Voucher) as-is: that mixin's own
    vocabulary has no separate terminal "rejected" value at all —
    `apps.approvals.services.reject()` bounces those straight back to
    DRAFT, so DRAFT already covers it. A richer Status's own terminal,
    non-posted value (RecurringEntry's `cancelled`) can be added to
    the tuple IF AND ONLY IF reaching that status genuinely guarantees
    zero real movement — found live while wiring this up: Invoice's
    own `cancelled` is NOT such a case (`void_invoice` only runs on an
    already-ISSUED invoice and posts a real reversal entry — a voided
    invoice has real history and must stay 409 forever, so Invoice
    keeps the plain default), and RecurringEntry's `cancelled` needed
    its own extra `_extra_delete_guard` override below for the exact
    same reason (cancel only stops FUTURE due installments — an
    already-generated one's own posted JournalEntry survives
    untouched, see apps.accounting.recurring.cancel_recurring_entry).

    `_extra_delete_guard(instance)` is the override point for that
    kind of model-specific "status says deletable but check something
    else too" case — return a `Response` (409) to block, or `None` to
    let the generic status check's own verdict stand.
    """

    deletable_statuses = ("draft",)

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)

    def _extra_delete_guard(self, instance):
        return None

    def destroy(self, request, *args, **kwargs):
        from apps.platform.models import AuditLog
        from apps.platform.services import log_action

        instance = self.get_object()
        if instance.status not in self.deletable_statuses:
            return Response(
                {
                    "detail": _(
                        "This document has a posted/pending movement and cannot be deleted — "
                        "use withdraw/reverse/cancel instead."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )
        guard_response = self._extra_delete_guard(instance)
        if guard_response is not None:
            return guard_response
        instance.deleted_at = timezone.now()
        instance.deleted_by = request.user
        instance.save(update_fields=["deleted_at", "deleted_by"])
        self._after_soft_delete(instance)

        model = type(instance)
        target_type = f"{model._meta.app_label}.{model._meta.model_name}"
        log_action(
            actor_type=AuditLog.ActorType.TENANT_USER, actor_id=request.user.id,
            action=f"{target_type}.deleted", target_type=target_type, target_id=instance.pk,
            tenant_id=request.user.tenant_id, before={"status": instance.status}, request=request,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _after_soft_delete(self, instance):
        """Override point for a model-specific cleanup side effect that
        must run right after a successful soft delete — e.g.
        RecurringEntryViewSet detaching Asset.depreciation_entry so a
        deleted DRAFT schedule can't keep blocking a fresh one."""
        return None
