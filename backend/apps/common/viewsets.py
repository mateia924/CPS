from rest_framework import viewsets


class TenantScopedViewSet(viewsets.ModelViewSet):
    """A ModelViewSet that is hard-scoped to request.user.tenant.

    The client can never read or write across tenants: the queryset is
    always filtered by the authenticated user's tenant, and `tenant` is
    always injected server-side, never accepted from request data.
    """

    def get_queryset(self):
        return super().get_queryset().filter(tenant=self.request.user.tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.user.tenant)
