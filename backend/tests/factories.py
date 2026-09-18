import factory
from factory.django import DjangoModelFactory

from apps.access.models import Role
from apps.accounts.models import User
from apps.organization.models import CostCenter, LegalEntity
from apps.platform.models import Plan, PlatformUser
from apps.platform.services import generate_totp_secret
from apps.sales.models import Customer, Product
from apps.tenants.models import Tenant


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
