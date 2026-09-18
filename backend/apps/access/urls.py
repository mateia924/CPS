from rest_framework.routers import DefaultRouter

from .views import PermissionViewSet, RoleViewSet, UserViewSet

router = DefaultRouter()
router.register("roles", RoleViewSet, basename="role")
router.register("permissions", PermissionViewSet, basename="permission")
router.register("users", UserViewSet, basename="access-user")

urlpatterns = router.urls
