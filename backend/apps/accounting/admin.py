from django.contrib import admin

from .models import Account, JournalEntry, JournalLine


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "type", "tenant", "is_system")
    list_filter = ("tenant", "type")
    search_fields = ("code", "name")


class JournalLineInline(admin.TabularInline):
    model = JournalLine
    extra = 0


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    # Sprint 7.2.7 (§8.7, site 4 of 7): produced_by replaces source_type here.
    list_display = ("date", "memo", "tenant", "produced_by")
    list_filter = ("tenant", "produced_by")
    inlines = [JournalLineInline]
