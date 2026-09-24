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
        # Sprint 5.0: the voucher engine itself is 5.3 — these exist now
        # so the rule can be configured (and, per decision 4, the
        # matching amount is the voucher's base-currency total) before
        # any voucher actually reaches submit_for_approval().
        VOUCHER_RECEIPT = "voucher_receipt", _("Receipt Voucher")
        VOUCHER_PAYMENT = "voucher_payment", _("Payment Voucher")
        VOUCHER_SETTLEMENT = "voucher_settlement", _("Settlement Voucher")
        # Sprint 5.5 (block 5.5.0, CFO_REVIEW_1 C10): a fixed rule
        # (min_amount=0, required_role=Owner) is seeded for every tenant
        # and is NOT meant to be deletable/editable from the "قواعد
        # الاعتماد" screen — 3.15.9 requires approval on every IBAN
        # change, with no amount threshold to fall below.
        IBAN_CHANGE = "iban_change", _("IBAN Change Request")
        # Sprint 6.3 (decision 8): fixed rule (min_amount=0, required_
        # role=Owner) seeded per tenant, same "not deletable/editable"
        # treatment as IBAN_CHANGE — 3.16.3 requires the Owner (or the
        # sole user in a simplified-mode tenant) to approve every
        # opening balance, no amount threshold to configure away.
        OPENING_BALANCE = "opening_balance", _("Opening Balance")

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
