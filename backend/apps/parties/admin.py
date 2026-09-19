from django.contrib import admin

from .models import Party, PartyRole


class PartyRoleInline(admin.TabularInline):
    model = PartyRole
    extra = 0


@admin.register(Party)
class PartyAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "party_type", "is_active", "tenant")
    search_fields = ("code", "name", "tax_number")
    inlines = [PartyRoleInline]
