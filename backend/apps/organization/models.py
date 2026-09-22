from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import TenantScopedModel


class LegalEntity(TenantScopedModel):
    """A node in the legal tree (docs/SYSTEM_ANALYSIS.md 3.1): holding /
    sibling company / branch, unlimited depth via `parent`. Distinct from
    CostCenter below — this tree has financial ownership, a tax number
    and issues documents; the cost-center tree never does.
    """

    class Type(models.TextChoices):
        HOLDING = "holding", _("Holding")
        COMPANY = "company", _("Company")
        BRANCH = "branch", _("Branch")

    class TaxPeriodType(models.TextChoices):
        MONTHLY = "monthly", _("Monthly")
        QUARTERLY = "quarterly", _("Quarterly")

    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )
    code = models.CharField(_("code"), max_length=20)
    name = models.CharField(_("name"), max_length=255)
    entity_type = models.CharField(_("type"), max_length=20, choices=Type.choices)
    country_code = models.CharField(_("country code"), max_length=2, default="SA")
    tax_number = models.CharField(_("tax number"), max_length=50, blank=True)
    base_currency = models.CharField(_("base currency"), max_length=3, default="SAR")
    # Sprint 4.6 (3.16.2): "توليد تلقائي للسنة الحالية حسب نوع الفترة
    # المختار في إعدادات الكيان" — drives
    # accounting.services.generate_tax_periods_for_year.
    tax_period_type = models.CharField(
        _("tax period type"), max_length=10, choices=TaxPeriodType.choices, default=TaxPeriodType.MONTHLY
    )
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["code"]
        verbose_name_plural = "legal entities"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "code"], name="unique_legal_entity_code_per_tenant"
            )
        ]

    def __str__(self):
        return f"{self.code} {self.name}"

    def clean(self):
        if not self.parent_id:
            return
        if self.parent_id == self.id:
            raise ValidationError(_("An entity cannot be its own parent."))
        if self.parent.entity_type == self.Type.BRANCH:
            raise ValidationError(_("A branch cannot have child entities."))
        node = self.parent
        seen = set()
        while node is not None:
            if node.id == self.id or node.id in seen:
                raise ValidationError(
                    _("This would create a cycle in the legal entity tree.")
                )
            seen.add(node.id)
            node = node.parent


class CostCenter(TenantScopedModel):
    """A node in the analytical/profitability tree (3.1, 3.2) — never
    issues documents, never has a "chart of accounts" type of its own
    (the account is the independent second analytical dimension).
    """

    class Type(models.TextChoices):
        DEPARTMENT = "department", _("Department")
        VEHICLE = "vehicle", _("Vehicle")
        WAREHOUSE = "warehouse", _("Warehouse")
        EMPLOYEE = "employee", _("Employee")
        PROJECT = "project", _("Project")
        GENERAL = "general", _("General")

    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )
    code = models.CharField(_("code"), max_length=20)
    name = models.CharField(_("name"), max_length=255)
    center_type = models.CharField(_("type"), max_length=20, choices=Type.choices)

    # Optional link to an existing entity (employee, warehouse, ...) once
    # those exist in later sprints — "تسجيل مرة واحدة" (3.3). Nothing
    # points at this yet; it's forward-compatible plumbing only.
    linked_content_type = models.ForeignKey(
        ContentType, null=True, blank=True, on_delete=models.SET_NULL
    )
    linked_object_id = models.UUIDField(null=True, blank=True)
    linked_object = GenericForeignKey("linked_content_type", "linked_object_id")

    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "code"], name="unique_cost_center_code_per_tenant"
            )
        ]

    def __str__(self):
        return f"{self.code} {self.name}"

    def clean(self):
        if not self.parent_id:
            return
        if self.parent_id == self.id:
            raise ValidationError(_("A cost center cannot be its own parent."))
        node = self.parent
        seen = set()
        while node is not None:
            if node.id == self.id or node.id in seen:
                raise ValidationError(
                    _("This would create a cycle in the cost center tree.")
                )
            seen.add(node.id)
            node = node.parent
