from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    InventorySettingsView,
    ItemBarcodeViewSet,
    ItemCategoryViewSet,
    ItemUoMViewSet,
    StockDocumentViewSet,
    StockLevelViewSet,
    UnitOfMeasureViewSet,
    WarehouseViewSet,
)

router = DefaultRouter()
router.register("inventory/item-categories", ItemCategoryViewSet, basename="item-category")
router.register("inventory/units", UnitOfMeasureViewSet, basename="unit-of-measure")
router.register("inventory/item-uoms", ItemUoMViewSet, basename="item-uom")
router.register("inventory/item-barcodes", ItemBarcodeViewSet, basename="item-barcode")
router.register("warehouses", WarehouseViewSet, basename="warehouse")
router.register("stock-documents", StockDocumentViewSet, basename="stock-document")
router.register("stock-levels", StockLevelViewSet, basename="stock-level")

urlpatterns = [
    path("inventory/settings/", InventorySettingsView.as_view(), name="inventory-settings"),
    path("", include(router.urls)),
]
