from rest_framework.routers import DefaultRouter

from .views import (
    AffiliatePartyViewSet,
    CustomerPartyViewSet,
    EmployeePartyViewSet,
    PartyViewSet,
    SupplierPartyViewSet,
)

router = DefaultRouter()
# Sprint 3.5: dedicated per-role screens registered *before* the
# catch-all "parties" prefix so /api/parties/customers/ resolves to
# CustomerPartyViewSet, not PartyViewSet's detail route with pk="customers".
router.register("parties/customers", CustomerPartyViewSet, basename="party-customer")
router.register("parties/suppliers", SupplierPartyViewSet, basename="party-supplier")
router.register("parties/employees", EmployeePartyViewSet, basename="party-employee")
router.register("parties/affiliates", AffiliatePartyViewSet, basename="party-affiliate")
router.register("parties", PartyViewSet, basename="party")

urlpatterns = router.urls
