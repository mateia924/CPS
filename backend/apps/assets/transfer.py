"""Sprint 6.5 (block 6.5.5, decision 8): moving an asset between cost
centers (always free) or legal entities (restricted to within one
company — inter-company transfer needs a between-entity journal entry
this project doesn't have yet, sprint 12's own README debt). No
journal entry, no approval: apps.accounting.recurring._generate_one
already reads `entry.legal_entity`/`entry.cost_center` off the parent
RecurringEntry at generation time, never a per-installment copy, so
updating those two fields here is the entire mechanism — a generated
installment's JournalLine is already historical and untouched."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from apps.organization.models import LegalEntity
from apps.platform.models import AuditLog
from apps.platform.services import log_action

from .models import Asset, AssetTransfer


def _company_root(entity):
    """The nearest ancestor that is not a branch — itself if it's
    already a HOLDING/COMPANY, its own parent if it's a BRANCH (a
    branch can never have child entities, so its parent is never a
    branch either — LegalEntity.clean() enforces this structurally)."""
    return entity.parent if entity.entity_type == LegalEntity.Type.BRANCH else entity


@transaction.atomic
def transfer_asset(asset, user, legal_entity=None, cost_center=None, request=None):
    if asset.status == Asset.Status.DISPOSED or asset.disposed_fraction >= 1:
        raise ValidationError(str(_("لا يمكن نقل أصل مُستبعَد بالكامل.")))

    changing_entity = legal_entity is not None and legal_entity.id != asset.legal_entity_id
    changing_cost_center = cost_center is not None and (
        asset.cost_center_id is None or cost_center.id != asset.cost_center_id
    )
    if not changing_entity and not changing_cost_center:
        raise ValidationError(str(_("لم يتغيّر الكيان القانوني أو مركز التكلفة.")))

    from_legal_entity = asset.legal_entity
    from_cost_center = asset.cost_center

    if changing_entity:
        if _company_root(asset.legal_entity).id != _company_root(legal_entity).id:
            raise ValidationError(
                str(_("النقل بين شركتين قانونيتين يتطلب القيد البيني — سبرنت 12."))
            )
        asset.legal_entity = legal_entity

    if changing_cost_center:
        asset.cost_center = cost_center

    update_fields = []
    if changing_entity:
        update_fields.append("legal_entity")
    if changing_cost_center:
        update_fields.append("cost_center")
    asset.save(update_fields=update_fields)

    entry = asset.depreciation_entry
    if entry is not None:
        entry_update_fields = []
        if changing_entity:
            entry.legal_entity = asset.legal_entity
            entry_update_fields.append("legal_entity")
        if changing_cost_center:
            entry.cost_center = asset.cost_center
            entry_update_fields.append("cost_center")
        if entry_update_fields:
            entry.save(update_fields=entry_update_fields)

    transfer = AssetTransfer.objects.create(
        tenant=asset.tenant, asset=asset,
        from_legal_entity=from_legal_entity, to_legal_entity=asset.legal_entity,
        from_cost_center=from_cost_center, to_cost_center=asset.cost_center,
        created_by=user,
    )
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER, actor_id=user.id, action="asset_transfer.created",
        target_type="asset", target_id=asset.id, tenant_id=asset.tenant_id,
        after={
            "to_legal_entity": str(asset.legal_entity_id), "to_cost_center": str(asset.cost_center_id or ""),
        },
        request=request,
    )
    return transfer
