from django.contrib import admin

from .models import Customer, Invoice, InvoiceLine, Product


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "email", "phone")
    list_filter = ("tenant",)
    search_fields = ("name", "email")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("sku", "name", "tenant", "unit_price", "tax_rate", "is_active")
    list_filter = ("tenant", "is_active")
    search_fields = ("sku", "name")


class InvoiceLineInline(admin.TabularInline):
    model = InvoiceLine
    extra = 0


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("number", "tenant", "customer", "status", "issue_date", "total")
    list_filter = ("tenant", "status")
    search_fields = ("number",)
    inlines = [InvoiceLineInline]
