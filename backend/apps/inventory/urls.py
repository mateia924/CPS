from django.urls import path

from .views import InventorySettingsView

urlpatterns = [
    path("inventory/settings/", InventorySettingsView.as_view(), name="inventory-settings"),
]
