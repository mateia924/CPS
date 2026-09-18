import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class Tenant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_("company name"), max_length=255)
    subdomain = models.SlugField(_("subdomain"), max_length=63, unique=True)
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("tenant")
        verbose_name_plural = _("tenants")

    def __str__(self):
        return self.name
