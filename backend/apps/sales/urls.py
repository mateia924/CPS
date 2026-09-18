from rest_framework.routers import DefaultRouter

from .views import CustomerViewSet, InvoiceViewSet, ProductViewSet

router = DefaultRouter()
router.register("customers", CustomerViewSet, basename="customer")
router.register("products", ProductViewSet, basename="product")
router.register("invoices", InvoiceViewSet, basename="invoice")

urlpatterns = router.urls
