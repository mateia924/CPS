from django.utils.translation import gettext_lazy as _


class TenantLimitExceeded(Exception):
    """Raised by the check_*_limit functions below; views catch this and
    respond 402 (sprint 2 spec: "تجاوز حد ... يرجع 402")."""

    def __init__(self, message):
        self.message = message
        super().__init__(message)


def apply_plan_to_tenant(tenant, plan):
    """3.13/sprint 2: changing a tenant's plan updates its feature flags
    immediately — TenantFeatures is the single source of truth every
    other app already reads (sidebar visibility, invoice legal_entity
    picker, etc.), so nothing else needs to change."""
    from .models import TenantFeatures

    tenant.plan = plan
    tenant.save(update_fields=["plan"])
    features, _created = TenantFeatures.objects.get_or_create(tenant=tenant)
    features.organization = plan.feature_organization
    features.cost_centers = plan.feature_cost_centers
    features.inventory = plan.feature_inventory
    features.purchasing = plan.feature_purchasing
    features.hr = plan.feature_hr
    features.treasury = plan.feature_treasury
    features.assets = plan.feature_assets
    features.save()


def check_user_limit(tenant):
    if tenant.plan is None or tenant.plan.max_users is None:
        return
    active_count = tenant.users.filter(is_active=True).count()
    if active_count >= tenant.plan.max_users:
        raise TenantLimitExceeded(
            _(
                "You've reached the maximum number of users allowed by your "
                "current plan (%(max)s). Upgrade your plan to add more."
            )
            % {"max": tenant.plan.max_users}
        )


def check_branch_limit(tenant):
    if tenant.plan is None or tenant.plan.max_branches is None:
        return
    from apps.organization.models import LegalEntity

    count = LegalEntity.objects.filter(
        tenant=tenant, entity_type=LegalEntity.Type.BRANCH, is_active=True
    ).count()
    if count >= tenant.plan.max_branches:
        raise TenantLimitExceeded(
            _(
                "You've reached the maximum number of branches allowed by "
                "your current plan (%(max)s). Upgrade your plan to add more."
            )
            % {"max": tenant.plan.max_branches}
        )


def check_invoice_limit(tenant):
    if tenant.plan is None or tenant.plan.max_invoices_per_month is None:
        return
    from django.utils import timezone

    from apps.sales.models import Invoice

    today = timezone.localdate()
    count = Invoice.objects.filter(
        tenant=tenant, created_at__year=today.year, created_at__month=today.month
    ).count()
    if count >= tenant.plan.max_invoices_per_month:
        raise TenantLimitExceeded(
            _(
                "You've reached the maximum number of invoices per month "
                "allowed by your current plan (%(max)s). Upgrade your plan "
                "to create more."
            )
            % {"max": tenant.plan.max_invoices_per_month}
        )
