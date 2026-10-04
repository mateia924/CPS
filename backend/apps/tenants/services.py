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
    # Sprint 6.6.3 (item 1): `.using(tenant._state.db)`, not a bare
    # manager call — this function runs both from registration (the
    # "default" alias, having just SET LOCAL cps.tenant_id to this very
    # tenant — see RegisterSerializer.create()) and from apps.platform.
    # views.TenantAdminViewSet.change_plan (the "platform" alias, no
    # RLS at all) — a bare TenantFeatures.objects query always targets
    # "default" regardless of which alias `tenant` itself was loaded
    # from, which would silently mis-target "default" (and fail its
    # RLS check outright) when called from the platform path. Adopting
    # the caller's own alias makes this correct either way.
    features, _created = TenantFeatures.objects.using(tenant._state.db).get_or_create(tenant=tenant)
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


def configure_database_roles_and_rls(connection):
    """Sprint 6.6.3 (item 1): the ONE place that (idempotently) sets up
    everything RLS needs — called both from the setup migration
    (apps.tenants.migrations.0016_row_level_security) and from
    `manage.py setup_rls` (apps.tenants.management.commands.setup_rls),
    which `scripts/staging_refresh.sh` re-runs after every restore,
    since `pg_dump --no-privileges` (backup.sh, sprint 6.6.0) strips
    every GRANT from the dump — a restored database's tables have NO
    privileges for `cps_app` at all until this runs again.

    Must be called with a connection whose role can do DDL (table
    owner or superuser) — i.e. the same role `manage.py migrate` itself
    already runs as, never `cps_app`.

    1. Creates `cps_app` (POSTGRES_APP_USER/PASSWORD env vars) if
       missing — NOSUPERUSER NOBYPASSRLS explicitly, though that's
       already the default for a freshly created role; explicit here
       in case the role pre-exists with different flags from a prior
       manual attempt. This is the tenant-web-request-serving role
       (docker-compose's APP_DATABASE_URL, gunicorn's own connection on
       docker-compose.local.yml/staging.yml — never docker-compose.
       dev.yml, which stays on the unrestricted role since it's
       explicitly not a UAT/production stand-in, sprint 6.6.0).
    2. Grants it CONNECT/USAGE + SELECT/INSERT/UPDATE/DELETE on every
       current table and sequence, plus ALTER DEFAULT PRIVILEGES so a
       table a FUTURE migration creates is covered automatically
       without a third place needing to remember this.
    3. Enables row-level security and installs one policy per table
       from apps.common.rls.tenant_scoped_tables() — every table
       carrying a `tenant_id` column gets `USING (tenant_id =
       current_setting('cps.tenant_id', true)::uuid)`. The `true`
       (missing_ok) argument is what makes "no request context at all"
       resolve to NULL rather than raise — NULL never equals a real
       tenant_id, so a bare `Model.objects.all()` outside any tenant
       request, or under apps.tenants.middleware.RLSTenantMiddleware
       before it has set anything, returns zero rows rather than
       erroring or leaking.

    Superusers (this project's original `cps` role, still what
    migrations/management commands/Celery/the "platform" DB alias all
    connect as) ALWAYS bypass RLS regardless of any policy — that's
    exactly the "دور منفصل يملك التجاوز" the spec asks for, with no
    separate role needed for it: it's simply the role that already
    existed before this sprint.
    """
    from django.conf import settings

    from apps.common.rls import tenant_scoped_tables

    if connection.vendor != "postgresql":
        return

    app_user = settings.POSTGRES_APP_USER
    app_password = settings.POSTGRES_APP_PASSWORD
    if not app_user or not app_password:
        raise RuntimeError(
            "POSTGRES_APP_USER/POSTGRES_APP_PASSWORD must be set to configure the "
            "restricted app role (apps.tenants.services.configure_database_roles_and_rls)."
        )

    quoted_user = connection.ops.quote_name(app_user)
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [app_user])
        if cursor.fetchone() is None:
            cursor.execute(f"CREATE ROLE {quoted_user} LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD %s", [app_password])
        else:
            cursor.execute(f"ALTER ROLE {quoted_user} LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD %s", [app_password])

        cursor.execute(f'GRANT CONNECT ON DATABASE {connection.ops.quote_name(connection.settings_dict["NAME"])} TO {quoted_user}')
        cursor.execute(f"GRANT USAGE ON SCHEMA public TO {quoted_user}")
        cursor.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {quoted_user}")
        cursor.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {quoted_user}")
        cursor.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {quoted_user}"
        )
        cursor.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {quoted_user}")

        # Sprint 7.0 (found while adding apps.inventory.InventorySettings
        # — the first new tenant-scoped table added since this migration
        # 0016 itself was written): tenant_scoped_tables() reads the
        # LIVE, current model registry, not this migration's own
        # historical state — so on a cold `--create-db` replay, by the
        # time 0016's RunPython executes, Django's migration graph may
        # not yet have created a table a LATER migration (in another
        # app, e.g. apps.inventory.0001) will create — "relation ...
        # does not exist". Skipping it here is correct and complete:
        # scripts/deploy.sh now runs `manage.py setup_rls` (this same
        # function) after every migrate (sprint-7.md §0 rule 4), so any
        # table 0016 had to skip gets its policy from that very next
        # call — never silently uncovered in a real database.
        cursor.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
        existing_tables = {row[0] for row in cursor.fetchall()}

        for db_table, _model in tenant_scoped_tables():
            if db_table not in existing_tables:
                continue
            quoted_table = connection.ops.quote_name(db_table)
            policy_name = "tenant_isolation"
            cursor.execute(f"ALTER TABLE {quoted_table} ENABLE ROW LEVEL SECURITY")
            # Always drop + recreate (not "only if missing") so re-
            # running this — scripts/staging_refresh.sh does, after
            # every restore — always installs the CURRENT policy
            # expression, never a stale one from an earlier version of
            # this function. Sprint 6.6.3 bug found via tests/test_rls.
            # py: current_setting('cps.tenant_id', true) returns NULL
            # only when the GUC was never set in this transaction at
            # all — once explicitly `SET LOCAL ... = DEFAULT` (a fresh
            # connection's placeholder custom GUC "default"), it
            # returns '' (empty string), and ''::uuid raises instead of
            # comparing false. NULLIF(...,'') normalizes both cases to
            # NULL, which a tenant_id column can never equal — zero
            # rows either way, never an error.
            cursor.execute(f"DROP POLICY IF EXISTS {policy_name} ON {quoted_table}")
            cursor.execute(
                f"CREATE POLICY {policy_name} ON {quoted_table} "
                "USING (tenant_id = NULLIF(current_setting('cps.tenant_id', true), '')::uuid)"
            )
