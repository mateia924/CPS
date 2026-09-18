from django.contrib import admin

from .models import CostCenter, LegalEntity


@admin.register(LegalEntity)
class LegalEntityAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "tenant", "entity_type", "parent", "is_active")
    list_filter = ("tenant", "entity_type", "is_active")
    search_fields = ("code", "name")


@admin.register(CostCenter)
class CostCenterAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "tenant", "center_type", "parent", "is_active")
    list_filter = ("tenant", "center_type", "is_active")
    search_fields = ("code", "name")
