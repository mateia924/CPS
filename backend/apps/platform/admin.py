from django.contrib import admin

from .models import AuditLog, Plan, PlatformUser


@admin.register(PlatformUser)
class PlatformUserAdmin(admin.ModelAdmin):
    list_display = ("email", "full_name", "role", "is_active", "totp_confirmed")
    search_fields = ("email", "full_name")


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active", "max_users", "max_branches")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor_type", "actor_id", "action", "tenant_id")
    list_filter = ("actor_type", "action")
    search_fields = ("action",)

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
