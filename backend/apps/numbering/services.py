from django.db import transaction
from django.utils import timezone

from .models import DocumentNumberingSetting, DocumentSequence

# Sensible defaults used only the first time a doc_type is numbered for a
# tenant — the settings screen can change the prefix afterwards without
# affecting numbers already issued (only the *next* number is affected).
DEFAULT_PREFIXES = {
    "invoice": "INV",
    "party_customer": "CUS",
    "party_supplier": "SUP",
    "party_employee": "EMP",
    "party_affiliate": "AFF",
    "journal_entry": "JV",
}


def get_or_create_numbering_setting(tenant, doc_type):
    setting, _created = DocumentNumberingSetting.objects.get_or_create(
        tenant=tenant,
        doc_type=doc_type,
        defaults={"prefix": DEFAULT_PREFIXES.get(doc_type, doc_type.upper()[:6])},
    )
    return setting


@transaction.atomic
def next_document_number(tenant, doc_type, legal_entity=None, date=None):
    """Atomic, gap-free, per-(tenant, doc_type, legal_entity, year) or
    per-(tenant, doc_type, legal_entity) counter — ARCH_REVIEW_1.md
    §3.4's design, implemented literally: select_for_update() locks
    only the one DocumentSequence row being incremented (not the whole
    table), so concurrent callers for a *different* scope never block
    each other, and two concurrent callers for the *same* scope are
    serialized correctly (Django's documented get_or_create-under-a-
    unique-constraint pattern handles the create-vs-create race; see
    the model's nulls_distinct=False constraint for why that matters
    here specifically).

    `legal_entity=None` is valid and deliberate for doc types with no
    legal-entity dimension (see DocumentSequence.legal_entity) — every
    such doc_type then shares one sequence per tenant across all
    entities.

    Correction after 4.1 (Decision Log): the *sequence* stays scoped
    per legal_entity (each branch keeps its own independent counter),
    but the *displayed* number must stay unique across the whole tenant
    (ZATCA: unique per tax registration, which branches normally
    share) — so once a tenant has more than one branch/company, the
    entity's code is folded into the string to keep two branches' own
    "00001"s from colliding as text. DocumentNumberingSetting.
    include_entity_code can force this on/off per doc_type instead of
    the automatic (simplified-mode) choice.
    """
    date = date or timezone.localdate()
    setting = get_or_create_numbering_setting(tenant, doc_type)
    scope_year = date.year if setting.reset_yearly else 0

    sequence, _created = DocumentSequence.objects.select_for_update().get_or_create(
        tenant=tenant, doc_type=doc_type, legal_entity=legal_entity, year=scope_year,
    )
    sequence.last_number += 1
    sequence.save(update_fields=["last_number"])

    include_entity_code = setting.include_entity_code
    if include_entity_code is None:
        # "تلقائي حسب عدد الكيانات": counting *branches* specifically,
        # not every LegalEntity row — a standalone company or the
        # standard one-company-one-branch setup (the small-client
        # default, 3.13) both have exactly one real invoicing point, so
        # neither should get an entity code. Only once a tenant has more
        # than one branch does a number collision risk actually exist.
        if legal_entity is None:
            include_entity_code = False
        else:
            from apps.organization.models import LegalEntity

            branch_count = LegalEntity.objects.filter(
                tenant=tenant, entity_type=LegalEntity.Type.BRANCH, is_active=True
            ).count()
            include_entity_code = branch_count > 1

    if include_entity_code and legal_entity is not None:
        return f"{setting.prefix}-{legal_entity.code}-{date.year}-{sequence.last_number:05d}"
    return f"{setting.prefix}-{date.year}-{sequence.last_number:05d}"
