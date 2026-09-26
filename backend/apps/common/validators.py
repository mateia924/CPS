import re

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

# Sprint 5.6 (block 5.6, company settings screen): "الرقم الضريبي
# السعودي 15 رقمًا يبدأ وينتهي بـ3، السجل التجاري 10 أرقام." Kept here
# (not inline in the serializer) so 5.7's C16 (broader Saudi format
# validation — national ID/CR wherever else it's entered) can import
# these instead of re-deriving them.


def validate_saudi_tax_number(value):
    if not value:
        return
    if len(value) != 15 or not value.isdigit() or value[0] != "3" or value[-1] != "3":
        raise ValidationError(
            _("Saudi tax number must be 15 digits, starting and ending with 3.")
        )


def validate_saudi_commercial_registration(value):
    if not value:
        return
    if len(value) != 10 or not value.isdigit():
        raise ValidationError(_("Commercial registration number must be 10 digits."))


def future_date_warning(doc_date):
    """CFO_REVIEW_1 F1: a future-dated document is a warning, never a
    block (fiscal periods that could actually enforce this arrive in
    sprint 6) — returns a list so every caller can just `+` it onto its
    own warnings[]."""
    if doc_date and doc_date > timezone.localdate():
        return [str(_("This document is dated in the future."))]
    return []


def validate_saudi_national_id(value):
    """Sprint 5.7 (CFO_REVIEW_1 C16): "الهوية/الإقامة (10 أرقام تبدأ 1
    أو 2)" — 1 for a Saudi national ID, 2 for a resident's iqama."""
    if not value:
        return
    if len(value) != 10 or not value.isdigit() or value[0] not in ("1", "2"):
        raise ValidationError(
            _("Saudi national ID / iqama number must be 10 digits, starting with 1 or 2.")
        )


_IBAN_COUNTRY_LENGTHS = {"SA": 24, "EG": 29}


def validate_iban(value, country_code=None):
    """Sprint 5.5 (block 5.5.0, CPS_PARITY_PLAN v2 decision 7): general
    IBAN shape (two-letter country + two check digits + 11-30
    alphanumerics, no spaces) plus a mandatory ISO 7064 mod-97 checksum
    — this is *only* applied to a value a user actually types going
    forward; the one-time data migration that backfills
    Party.iban from the old free-text PartyRole.details["iban"] bag
    never calls this (see 0002_backfill_party_iban_from_role_details.py
    — a pre-existing placeholder value there is expected to fail this
    check, and correcting it is exactly what forces it through
    IbanChangeRequest instead of a silent edit)."""
    if not value:
        return
    value = value.strip().upper().replace(" ", "")
    if len(value) < 15 or len(value) > 34 or not value[:2].isalpha() or not value[2:4].isdigit():
        raise ValidationError(_("Invalid IBAN format."))
    if not value[4:].isalnum():
        raise ValidationError(_("Invalid IBAN format."))
    expected_length = _IBAN_COUNTRY_LENGTHS.get(value[:2])
    if expected_length is not None and len(value) != expected_length:
        raise ValidationError(
            _("IBAN for %(country)s must be %(length)s characters long.")
            % {"country": value[:2], "length": expected_length}
        )
    if country_code and country_code in _IBAN_COUNTRY_LENGTHS and value[:2] != country_code:
        raise ValidationError(
            _("IBAN country prefix (%(iban_country)s) does not match the party's country (%(country)s).")
            % {"iban_country": value[:2], "country": country_code}
        )
    # ISO 7064 mod-97: move the first four characters to the end, map
    # every letter to two digits (A=10 ... Z=35), then the whole string
    # mod 97 must equal 1.
    rearranged = value[4:] + value[:4]
    digits = "".join(str(int(ch, 36)) for ch in rearranged)
    if int(digits) % 97 != 1:
        raise ValidationError(_("IBAN checksum is invalid."))


# Sprint 6.9.1 (item I, decision 7): "معرّف الشركة" (the subdomain) is
# a real routing identifier a customer picks once at registration and
# can never change — the rules were previously only "Django's
# SlugField" (which also accepts underscores and uppercase, neither
# wanted here). Called from RegisterSerializer only — not attached to
# Tenant.subdomain's own `validators=` kwarg, which would change the
# field's migration state for zero actual DB-level effect (validators
# aren't a Postgres constraint); one function, one call site, no
# migration needed.
_SUBDOMAIN_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,28}[a-z0-9])?$")

RESERVED_SUBDOMAINS = {
    "www", "app", "api", "admin", "mail", "static", "media", "cdn",
    "status", "help", "support", "docs", "login", "register", "platform",
}


def validate_tenant_subdomain(value):
    value = (value or "").strip().lower()
    if not _SUBDOMAIN_PATTERN.match(value):
        raise ValidationError(
            _(
                "اسم الشركة في الرابط يجب أن يكون 3 إلى 30 حرفًا، حروفًا "
                "لاتينية صغيرة وأرقامًا وشرطات فقط، ولا يبدأ أو ينتهي بشرطة."
            )
        )
    if value in RESERVED_SUBDOMAINS:
        raise ValidationError(_("هذا الاسم محجوز، اختر اسمًا آخر."))
    return value
