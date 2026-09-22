from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import TenantScopedModel


class DocumentNumberingSetting(TenantScopedModel):
    """Sprint 4.1 (docs/SYSTEM_ANALYSIS.md 3.4; ARCH_REVIEW_1.md §3.4):
    per-(tenant, doc_type) prefix and yearly-reset choice. Settings ←
    "ترقيم المستندات" edits these; it never creates rows directly — the
    first call to services.next_document_number() for a given doc_type
    lazily creates one with a sensible default prefix (services.
    DEFAULT_PREFIXES), so numbering works correctly even for a doc_type
    an admin has never visited the settings screen for.
    """

    doc_type = models.CharField(_("document type"), max_length=30)
    prefix = models.CharField(_("prefix"), max_length=10)
    reset_yearly = models.BooleanField(_("reset numbering every year"), default=True)
    # Correction after 4.1 (Decision Log, SYSTEM_ANALYSIS.md §11): the
    # *sequence* stays scoped per (tenant, doc_type, legal_entity, year)
    # — each branch keeps its own independent counter — but the
    # *displayed* number must stay unique tenant-wide (ZATCA requires a
    # unique number per tax registration, and branches normally share
    # one tax number), so two branches' independently-incrementing
    # "00001" would otherwise collide as the same string. None (the
    # default) means "decide automatically": include the entity code
    # whenever the tenant is not in simplified mode (more than one
    # branch/company) — see services.next_document_number. True/False
    # override the automatic choice explicitly per doc_type.
    include_entity_code = models.BooleanField(
        _("include entity code in the number"), null=True, blank=True, default=None
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "doc_type"], name="unique_numbering_setting_per_doc_type"
            )
        ]

    def __str__(self):
        return f"{self.doc_type} ({self.prefix})"


class DocumentSequence(TenantScopedModel):
    """The atomic counter itself (ARCH_REVIEW_1.md §3.4's proposed
    design, implemented literally: select_for_update() inside
    transaction.atomic in services.next_document_number). Never
    created, read or edited directly by any view — internal only.
    """

    doc_type = models.CharField(max_length=30)
    # Null for doc types with no legal-entity dimension (party codes:
    # Party isn't tied to one legal entity in this schema) — a
    # deliberate, documented extension of the ARCH_REVIEW_1.md design,
    # which only considered legal-entity-scoped documents (invoices,
    # journal entries). See the Decision Log (SYSTEM_ANALYSIS.md §11).
    legal_entity = models.ForeignKey(
        "organization.LegalEntity", null=True, blank=True, on_delete=models.CASCADE
    )
    year = models.PositiveIntegerField()
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "doc_type", "legal_entity", "year"],
                name="unique_document_sequence_scope",
                # Postgres treats NULL as distinct by default, which
                # would let two rows both with legal_entity=NULL
                # (every party-code scope) coexist and race — this
                # requires Postgres 15+ (project pins 16) and Django
                # 5.0+ (project pins 5.2 LTS), both already satisfied.
                nulls_distinct=False,
            )
        ]
