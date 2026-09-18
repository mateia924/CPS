import factory
from factory.django import DjangoModelFactory

from apps.accounts.models import User
from apps.sales.models import Customer, Product
from apps.tenants.models import Tenant


class TenantFactory(DjangoModelFactory):
    class Meta:
        model = Tenant

    name = factory.Sequence(lambda n: f"Test Tenant {n}")
    subdomain = factory.Sequence(lambda n: f"test-tenant-{n}")


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
