from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from .validators import validate_iban


def validate_iban_field(value, current_value, country_code=None):
    """Sprint 5.5 (block 5.5.0, CFO_REVIEW_1 C10): shared by every
    serializer that exposes an `iban` field (Party, Bank) — the first
    entry (current value empty) is a plain edit; changing an
    already-set value must go through treasury.IbanChangeRequest
    instead of a direct PATCH. Format/checksum (validate_iban) is only
    enforced on a value someone actually typed — never on data already
    sitting in the database (e.g. the one-time party-iban backfill
    migration, which never goes through a serializer at all)."""
    if not value or value == current_value:
        # No-op (re-submitting the exact current value, including a
        # placeholder that predates format validation) is never a
        # "change" and skips both checks below.
        return value
    if current_value:
        raise serializers.ValidationError(
            str(
                _(
                    "This IBAN is already set. Request a change from "
                    "«طلبات تغيير IBAN» instead of editing it directly."
                )
            )
        )
    try:
        validate_iban(value, country_code=country_code)
    except DjangoValidationError as exc:
        raise serializers.ValidationError(exc.message)
    return value
