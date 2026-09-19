from django.contrib import admin

from .models import Bank, CashBox, Custody


@admin.register(Bank)
class BankAdmin(admin.ModelAdmin):
    list_display = ("name", "bank_name", "legal_entity", "is_active", "tenant")


@admin.register(CashBox)
class CashBoxAdmin(admin.ModelAdmin):
    list_display = ("name", "legal_entity", "custodian", "is_active", "tenant")


@admin.register(Custody)
class CustodyAdmin(admin.ModelAdmin):
    list_display = ("name", "employee", "legal_entity", "is_active", "tenant")
