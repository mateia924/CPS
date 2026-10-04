"""Sprint 7.0 (docs/prompts/sprint-7.md, block 7.0): the scaffold —
inventory's five new system accounts (D1), the module gate (rule 1),
the new "Warehouse Keeper" role (D17), and the control-account rule
extended to INVENTORY. Everything else in sprint-7.md's own block 7.0
test list is already covered generically by the existing structural
suite (test_rls_structural.py, test_structural_isolation.py,
test_entity_scope_structural.py, test_tenant_isolation.py) — no new
model/URL this block adds is exempt from any of them.
"""

from io import StringIO

import pytest
from django.core.management import call_command

from apps.access.models import Role
from apps.access.services import seed_default_roles, user_has_permission
from apps.accounting.models import Account

from .factories import UserFactory


@pytest.mark.django_db
def test_add_missing_system_accounts_is_idempotent(tenant_a):
    """The five new inventory keys get created once, and a second run
    changes nothing — the exact test sprint-7.md's own block 7.0
    specifies ("تُضاف لمستأجر قائم بلا ازدواج وتشغيلة ثانية بلا
    تغيير"). The tenant_a fixture only runs seed_chart_of_accounts
    (the template), never this command — so the first call_command
    below is itself the real "add to an existing tenant" run; before/
    after is snapshotted around the SECOND call, which must be a
    true no-op."""
    for key in ("INVENTORY", "COGS", "INVENTORY_ADJUSTMENT", "GRNI", "GOODS_IN_TRANSIT"):
        assert Account.objects.filter(tenant=tenant_a, system_key=key).count() == 1

    call_command("add_missing_system_accounts", "--tenant", tenant_a.subdomain, stdout=StringIO())

    before = set(Account.objects.filter(tenant=tenant_a).values_list("id", "code", "system_key"))
    call_command("add_missing_system_accounts", "--tenant", tenant_a.subdomain, stdout=StringIO())
    after = set(Account.objects.filter(tenant=tenant_a).values_list("id", "code", "system_key"))
    assert before == after


@pytest.mark.django_db
def test_inventory_system_accounts_are_control_accounts(tenant_a):
    for key in ("INVENTORY", "COGS", "INVENTORY_ADJUSTMENT", "GRNI", "GOODS_IN_TRANSIT"):
        account = Account.objects.get(tenant=tenant_a, system_key=key)
        assert account.allow_manual_posting is False


@pytest.mark.django_db
def test_manual_jv_on_inventory_control_account_rejected_without_override(tenant_a, client_a):
    from apps.organization.models import LegalEntity

    branch = LegalEntity.objects.get(tenant=tenant_a, entity_type=LegalEntity.Type.BRANCH)
    cash = Account.objects.get(tenant=tenant_a, system_key="CASH")
    inventory = Account.objects.get(tenant=tenant_a, system_key="INVENTORY")

    response = client_a.post(
        "/api/journal-entries/",
        {
            "legal_entity": str(branch.id), "date": "2026-01-02",
            "lines": [
                {"account": str(cash.id), "debit_fc": "0", "credit_fc": "50.00"},
                {"account": str(inventory.id), "debit_fc": "50.00", "credit_fc": "0"},
            ],
        },
        format="json",
    )
    assert response.status_code == 400, response.data
    assert "رقابة" in response.data["detail"] or "control" in response.data["detail"].lower()


@pytest.mark.django_db
def test_tenant_without_inventory_module_gets_404(tenant_a, client_a):
    """rule 1: a tenant with TenantFeatures.inventory off doesn't just
    lack permission on /api/inventory/* — the module doesn't exist for
    them at all (404, not 403)."""
    assert tenant_a.features.inventory is False

    response = client_a.get("/api/inventory/settings/")
    assert response.status_code == 404

    tenant_a.features.inventory = True
    tenant_a.features.save(update_fields=["inventory"])
    response = client_a.get("/api/inventory/settings/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_warehouse_keeper_role_has_its_default_permissions(tenant_a):
    seed_default_roles(tenant_a)
    role = Role.objects.get(tenant=tenant_a, name="Warehouse Keeper", is_system=True)
    keeper = UserFactory(tenant=tenant_a, email="keeper@sprint7-block0.test")
    keeper.roles.add(role)

    assert user_has_permission(keeper, "inventory.view")
    assert user_has_permission(keeper, "inventory.manage")
    assert user_has_permission(keeper, "inventory.post")
    assert user_has_permission(keeper, "accounting.view")
    # D17: scoped to stock reports only — no chart-of-accounts editing,
    # no journal-entry posting authority.
    assert not user_has_permission(keeper, "accounting.manage")
    assert not user_has_permission(keeper, "vouchers.post")


@pytest.mark.django_db
def test_accountant_gets_inventory_view_and_post_but_not_manage(tenant_a):
    seed_default_roles(tenant_a)
    accountant_role = Role.objects.get(tenant=tenant_a, name="Accountant", is_system=True)
    accountant = UserFactory(tenant=tenant_a, email="accountant@sprint7-block0.test")
    accountant.roles.add(accountant_role)

    assert user_has_permission(accountant, "inventory.view")
    assert user_has_permission(accountant, "inventory.post")
    assert not user_has_permission(accountant, "inventory.manage")


@pytest.mark.django_db
def test_apply_item_feature_defaults_reads_item_features(tenant_a):
    """D18: driven purely by which feature strings are present, no
    activity-specific branch."""
    from apps.inventory.models import InventorySettings
    from apps.inventory.services import apply_item_feature_defaults

    settings_obj = apply_item_feature_defaults(tenant_a, ["serial_imei", "units", "barcode"])
    assert settings_obj.default_tracking == InventorySettings.Tracking.SERIAL
    assert settings_obj.units_enabled is True
    assert settings_obj.barcode_enabled is True
    assert settings_obj.show_weight_karat_fields is False

    settings_obj = apply_item_feature_defaults(tenant_a, ["batch_expiry", "weight_karat"])
    assert settings_obj.default_tracking == InventorySettings.Tracking.BATCH
    assert settings_obj.show_weight_karat_fields is True
