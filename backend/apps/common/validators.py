from django.core.exceptions import ValidationError
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
