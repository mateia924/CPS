from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.constants import MONEY_DECIMAL_PLACES, MONEY_MAX_DIGITS
from apps.common.models import TenantScopedModel


class ApprovalRule(TenantScopedModel):
    """Sprint 4.5 (docs/SYSTEM_ANALYSIS.md 3.15.1): الإعدادات ← "قواعد
    الاعتماد". A document of `doc_type` whose base-currency amount is
    >= `min_amount` requires `required_role` to approve it — matching
    is the highest-`min_amount` active rule the amount still qualifies
    for (a tiered-threshold model: e.g. >0 needs Accountant, >10000
    needs Owner). No matching rule at all = auto-approve on submit
    (services.submit_for_approval).
    """

    class DocType(models.TextChoices):
        JOURNAL_ENTRY = "journal_entry", _("Journal Entry")
        INVOICE = "invoice", _("Invoice")

    doc_type = models.CharField(_("document type"), max_length=30, choices=DocType.choices)
    min_amount = models.DecimalField(
        _("minimum amount"), max_digits=MONEY_MAX_DIGITS, decimal_places=MONEY_DECIMAL_PLACES, default=0
    )
    required_role = models.ForeignKey(
        "access.Role", on_delete=models.PROTECT, related_name="approval_rules"
    )
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["doc_type", "-min_amount"]

    def __str__(self):
        return f"{self.doc_type} >= {self.min_amount} -> {self.required_role}"
