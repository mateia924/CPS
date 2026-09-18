import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import TenantScopedModel


class Account(TenantScopedModel):
    class Type(models.TextChoices):
        ASSET = "asset", _("Asset")
        LIABILITY = "liability", _("Liability")
        EQUITY = "equity", _("Equity")
        REVENUE = "revenue", _("Revenue")
        EXPENSE = "expense", _("Expense")

    code = models.CharField(_("code"), max_length=20)
    name = models.CharField(_("name"), max_length=255)
    type = models.CharField(_("type"), max_length=20, choices=Type.choices)
    is_system = models.BooleanField(_("system account"), default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="unique_account_code_per_tenant")
        ]

    def __str__(self):
        return f"{self.code} {self.name}"


class JournalEntry(TenantScopedModel):
    date = models.DateField(_("date"))
    memo = models.CharField(_("memo"), max_length=255, blank=True)
    source_type = models.CharField(_("source type"), max_length=50, blank=True)
    source_id = models.UUIDField(_("source id"), null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.date} {self.memo}"


class JournalLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name="lines")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="journal_lines")
    debit = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.account.code} D{self.debit} C{self.credit}"
