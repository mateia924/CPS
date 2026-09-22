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
    """
    date = date or timezone.localdate()
    setting = get_or_create_numbering_setting(tenant, doc_type)
    scope_year = date.year if setting.reset_yearly else 0

    sequence, _created = DocumentSequence.objects.select_for_update().get_or_create(
        tenant=tenant, doc_type=doc_type, legal_entity=legal_entity, year=scope_year,
    )
    sequence.last_number += 1
    sequence.save(update_fields=["last_number"])

    return f"{setting.prefix}-{date.year}-{sequence.last_number:05d}"
