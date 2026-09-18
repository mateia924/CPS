from django.contrib import admin

from .models import Tenant, TenantFeatures


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("name", "subdomain", "is_active", "created_at")
    search_fields = ("name", "subdomain")


@admin.register(TenantFeatures)
class TenantFeaturesAdmin(admin.ModelAdmin):
    list_display = ("tenant", "organization", "cost_centers", "inventory", "purchasing", "hr")
