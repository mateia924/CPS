from django.core.management.base import BaseCommand

from apps.inventory.models import Warehouse, set_default_warehouse
from apps.organization.models import LegalEntity
from apps.tenants.models import Tenant


class Command(BaseCommand):
    """Sprint 7.2 (block spec, item 1): "إنشاء الكيان لا يُنشئ مستودعًا
    تلقائيًا إلا عند تفعيل الوحدة" — a legal entity never gets a
    warehouse just by existing; this is the explicit command that
    creates one, for every entity (across every active tenant, or a
    single one via --tenant) that doesn't already have one. Code
    "MAIN" for the entity's own first warehouse, named "المستودع
    الرئيسي" — idempotent (an entity that already has ANY warehouse,
    default or not, is skipped, never given a second one)."""

    help = "Create a default warehouse for every legal entity that doesn't have one yet."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", default=None, help="Subdomain — restrict to this tenant only.")

    def handle(self, *args, **options):
        entities = LegalEntity.objects.filter(
            deleted_at__isnull=True, tenant__features__inventory=True,
        ).exclude(tenant__status=Tenant.Status.ARCHIVED)
        if options["tenant"]:
            entities = entities.filter(tenant__subdomain=options["tenant"])

        created = 0
        for entity in entities.select_related("tenant"):
            if Warehouse.objects.filter(legal_entity=entity).exists():
                continue
            code = "MAIN"
            if Warehouse.objects.filter(tenant=entity.tenant, code=code).exists():
                suffix = 1
                while Warehouse.objects.filter(tenant=entity.tenant, code=f"{code}-{suffix}").exists():
                    suffix += 1
                code = f"{code}-{suffix}"
            warehouse = Warehouse.objects.create(
                tenant=entity.tenant, legal_entity=entity, code=code, name="المستودع الرئيسي",
            )
            set_default_warehouse(warehouse)
            created += 1
            self.stdout.write(f"{entity.tenant.subdomain}/{entity.code}: created warehouse {warehouse.code}")

        self.stdout.write(self.style.SUCCESS(f"Created {created} warehouse(s)."))
