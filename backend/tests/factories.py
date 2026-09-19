import factory
from factory.django import DjangoModelFactory

from apps.access.models import Role
from apps.accounts.models import User
from apps.assets.models import Asset
from apps.organization.models import CostCenter, LegalEntity
from apps.parties.models import Party, PartyRole
from apps.platform.models import Plan, PlatformUser
from apps.platform.services import generate_totp_secret
from apps.sales.models import Customer, Product
from apps.tenants.models import Tenant
from apps.treasury.models import Bank, CashBox, Custody


class PlanFactory(DjangoModelFactory):
    """Reuses the plan seeded by platform/migrations/0002_seed_plans.py
    for the given `code` (present in every test DB, since migrations
    always run) instead of creating a conflicting duplicate row."""

    class Meta:
        model = Plan
        django_get_or_create = ("code",)

    code = "enterprise"
    name = "Enterprise"
    feature_organization = True
    feature_cost_centers = True
    feature_inventory = True
    feature_purchasing = True
    feature_hr = True


class TenantFactory(DjangoModelFactory):
    class Meta:
        model = Tenant

    name = factory.Sequence(lambda n: f"Test Tenant {n}")
    subdomain = factory.Sequence(lambda n: f"test-tenant-{n}")
    plan = factory.SubFactory(PlanFactory)
    status = Tenant.Status.ACTIVE


class UserFactory(DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    tenant = factory.SubFactory(TenantFactory)
    email = factory.Sequence(lambda n: f"user{n}@example.test")
    first_name = "Test"
    last_name = "User"
    role = User.Role.OWNER
    is_staff = True

    @factory.post_generation
    def password(obj, create, extracted, **kwargs):
        obj.set_password(extracted or "TestPass!2026")
        if create:
            obj.save()


class CustomerFactory(DjangoModelFactory):
    class Meta:
        model = Customer

    tenant = factory.SubFactory(TenantFactory)
    name = factory.Sequence(lambda n: f"Customer {n}")
    email = factory.Sequence(lambda n: f"customer{n}@example.test")


class PartyFactory(DjangoModelFactory):
    """Sprint 3: a Party that already holds the CUSTOMER role — the
    direct drop-in replacement for the pre-sprint-3 CustomerFactory
    wherever a test just needs something invoiceable. Build a bare
    Party + PartyRoleFactory manually for any other role."""

    class Meta:
        model = Party
        skip_postgeneration_save = True

    tenant = factory.SubFactory(TenantFactory)
    code = factory.Sequence(lambda n: f"P-{n:04d}")
    name = factory.Sequence(lambda n: f"Party {n}")
    email = factory.Sequence(lambda n: f"party{n}@example.test")
    party_type = Party.Type.ORGANIZATION

    @factory.post_generation
    def customer_role(obj, create, extracted, **kwargs):
        if create:
            PartyRole.objects.create(party=obj, role=PartyRole.Role.CUSTOMER)


class PartyRoleFactory(DjangoModelFactory):
    class Meta:
        model = PartyRole

    party = factory.SubFactory(PartyFactory)
    role = PartyRole.Role.EMPLOYEE


class ProductFactory(DjangoModelFactory):
    class Meta:
        model = Product

    tenant = factory.SubFactory(TenantFactory)
    sku = factory.Sequence(lambda n: f"SKU-{n}")
    name = factory.Sequence(lambda n: f"Product {n}")
    unit_price = "100.00"
    tax_rate = "14.00"


class LegalEntityFactory(DjangoModelFactory):
    class Meta:
        model = LegalEntity

    tenant = factory.SubFactory(TenantFactory)
    code = factory.Sequence(lambda n: f"LE-{n}")
    name = factory.Sequence(lambda n: f"Legal Entity {n}")
    entity_type = LegalEntity.Type.COMPANY


class CostCenterFactory(DjangoModelFactory):
    class Meta:
        model = CostCenter

    tenant = factory.SubFactory(TenantFactory)
    code = factory.Sequence(lambda n: f"CC-{n}")
    name = factory.Sequence(lambda n: f"Cost Center {n}")
    center_type = CostCenter.Type.GENERAL


class BankFactory(DjangoModelFactory):
    class Meta:
        model = Bank

    tenant = factory.SubFactory(TenantFactory)
    legal_entity = factory.SubFactory(LegalEntityFactory)
    name = factory.Sequence(lambda n: f"Bank Account {n}")


class CashBoxFactory(DjangoModelFactory):
    class Meta:
        model = CashBox

    tenant = factory.SubFactory(TenantFactory)
    legal_entity = factory.SubFactory(LegalEntityFactory)
    name = factory.Sequence(lambda n: f"Cash Box {n}")


class CustodyFactory(DjangoModelFactory):
    class Meta:
        model = Custody

    tenant = factory.SubFactory(TenantFactory)
    legal_entity = factory.SubFactory(LegalEntityFactory)
    employee = factory.SubFactory(PartyFactory)
    name = factory.Sequence(lambda n: f"Custody {n}")


class AssetFactory(DjangoModelFactory):
    class Meta:
        model = Asset

    tenant = factory.SubFactory(TenantFactory)
    legal_entity = factory.SubFactory(LegalEntityFactory)
    code = factory.Sequence(lambda n: f"AST-{n:04d}")
    name = factory.Sequence(lambda n: f"Asset {n}")
    category = Asset.Category.EQUIPMENT
    purchase_date = "2026-01-01"
    purchase_cost = "1000.00"


class RoleFactory(DjangoModelFactory):
    class Meta:
        model = Role

    tenant = factory.SubFactory(TenantFactory)
    name = factory.Sequence(lambda n: f"Role {n}")
    is_system = False


class PlatformUserFactory(DjangoModelFactory):
    """Bypasses the interactive create_platform_user command (which
    requires a real terminal for 2FA enrollment) — sets a known
    totp_secret directly so tests can generate valid codes with
    apps.platform.services.verify_totp."""

    class Meta:
        model = PlatformUser
        skip_postgeneration_save = True

    email = factory.Sequence(lambda n: f"admin{n}@platform.test")
    full_name = "Test Admin"
    role = PlatformUser.Role.SUPER_ADMIN
    totp_secret = factory.LazyFunction(generate_totp_secret)
    totp_confirmed = True

    @factory.post_generation
    def password(obj, create, extracted, **kwargs):
        obj.set_password(extracted or "TestPass!2026")
        if create:
            obj.save()
