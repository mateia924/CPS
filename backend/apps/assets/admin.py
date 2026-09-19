from django.contrib import admin

from .models import Asset


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "category", "status", "legal_entity", "is_active", "tenant")
    search_fields = ("code", "name")
