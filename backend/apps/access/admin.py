from django.contrib import admin

from .models import Permission, Role, UserEntityAccess


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ("code", "description")
    search_fields = ("code",)


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "is_system")
    list_filter = ("tenant", "is_system")
    filter_horizontal = ("permissions",)


@admin.register(UserEntityAccess)
class UserEntityAccessAdmin(admin.ModelAdmin):
    list_display = ("user", "legal_entity")
    list_filter = ("legal_entity__tenant",)
