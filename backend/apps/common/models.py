import uuid

from django.db import models


class TenantScopedModel(models.Model):
    """Base for every business table: always carries the owning tenant.

    Never expose `tenant` as a writable API field — it is always set
    server-side from request.user.tenant. See apps/common/viewsets.py.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.CASCADE, related_name="%(class)ss"
    )

    class Meta:
        abstract = True
