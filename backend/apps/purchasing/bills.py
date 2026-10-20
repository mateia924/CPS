"""Sprint 8.1: supplier bills — service, expense and asset lines.

Workflow, same shape as apps.inventory's stock documents: create/update a
DRAFT, submit (-> the approvals engine, which also checks the mandatory
attachment rule), approve/reject/withdraw, post (the journal entry and,
for an ASSET line, the asset record), reverse (a full mirror entry).

D4 for these line types — at POSTED, in the bill's currency and rate:
  SERVICE/EXPENSE   Dr the line's account (cost center on the line)
  ASSET             Dr FIXED_ASSETS, and an Asset is created (R-8.7)
  deductible VAT    Dr VAT_INPUT
  non-deductible    folded into the line's own debit (R-8.6)
  reverse charge    Cr VAT_OUTPUT + Dr VAT_INPUT, same amount (or Dr the
                    line itself if non-deductible) — nothing owed for it
  Cr the supplier's sub-ledger account by the bill total.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounting.models import TaxCode
from apps.platform.models import AuditLog
from apps.platform.services import log_action

from .models import SupplierBill, SupplierBillLine, WithholdingTaxCode

CENTS = Decimal("0.01")
HUNDRED = Decimal("100")
DOC_TYPE = "supplier_bill"
# One target_type for every audit row of a bill (create/update/approval/
# post/reverse) — the approvals engine logs under the doc_type, so this
# matches it, and ChangeHistoryTab reads exactly this string.
TARGET_TYPE = DOC_TYPE


class SupplierBillLocked(Exception):
    """A non-draft bill can't be edited — the view maps this to 409."""


def _q(value):
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def _log(user, action, bill, request=None, after=None):
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER, actor_id=user.id, action=f"supplier_bill.{action}",
        target_type=TARGET_TYPE, target_id=bill.id, tenant_id=bill.tenant_id, after=after, request=request,
    )


# -- lines --------------------------------------------------------------------


def is_vat_deductible(line):
    """Non-deductible when either the line's switch or the code says so."""
    return line.vat_deductible and line.tax_code.deductible != TaxCode.Deductible.NONE


def compute_line(line):
    """Fills net/tax/capitalized/cost/payable/wht on an (unsaved or saved)
    line from qty, unit_price, tax_code, vat_deductible, wht_code."""
    line.net = _q(line.qty * line.unit_price)
    line.tax_amount = _q(line.net * line.tax_code.rate / HUNDRED)
    deductible = is_vat_deductible(line)
    line.capitalized_tax = Decimal("0") if deductible else line.tax_amount
    line.cost = line.net + line.capitalized_tax
    if line.tax_code.kind == TaxCode.Kind.REVERSE_CHARGE:
        # Self-assessed: the supplier invoiced the net only.
        line.payable = line.net
    else:
        line.payable = line.net + line.tax_amount
    if line.wht_code_id:
        base = line.net if line.wht_code.base == WithholdingTaxCode.Base.NET else line.net + line.tax_amount
        line.wht_base = base
        line.wht_amount = _q(base * line.wht_code.rate / HUNDRED)
    else:
        line.wht_base = Decimal("0")
        line.wht_amount = Decimal("0")
    return line


def resolve_bill_lines(tenant, supplier, raw_lines):
    """Raw API line dicts -> unsaved SupplierBillLine objects (computed).
    Every id is looked up inside `tenant`; every refusal names its line."""
    from apps.accounting.models import Account
    from apps.assets.models import Asset
    from apps.organization.models import CostCenter

    default_expense = None
    role = supplier_role(supplier)
    if role is not None and role.default_expense_account_id:
        default_expense = role.default_expense_account

    lines = []
    for index, raw in enumerate(raw_lines, start=1):
        line_type = raw.get("line_type")
        if line_type not in SupplierBillLine.LineType.values:
            raise ValidationError({"lines": [f"السطر {index}: نوع البند غير معروف — خدمة أو مصروف أو أصل."]})
        qty = raw.get("qty") or Decimal("1")
        if qty <= 0:
            raise ValidationError({"lines": [f"السطر {index}: الكمية يجب أن تكون أكبر من صفر."]})
        unit_price = raw.get("unit_price")
        if unit_price is None or unit_price <= 0:
            raise ValidationError({"lines": [f"السطر {index}: السعر يجب أن يكون أكبر من صفر."]})
        tax_code = TaxCode.objects.filter(tenant=tenant, id=raw.get("tax_code"), is_active=True).first()
        if tax_code is None:
            raise ValidationError({"lines": [f"السطر {index}: كود الضريبة غير موجود أو معطّل."]})
        cost_center = None
        if raw.get("cost_center"):
            cost_center = CostCenter.objects.filter(tenant=tenant, id=raw["cost_center"]).first()
            if cost_center is None:
                raise ValidationError({"lines": [f"السطر {index}: مركز التكلفة غير موجود."]})
        wht_code = None
        if raw.get("wht_code"):
            wht_code = WithholdingTaxCode.objects.filter(tenant=tenant, id=raw["wht_code"], is_active=True).first()
            if wht_code is None:
                raise ValidationError({"lines": [f"السطر {index}: كود الاستقطاع غير موجود أو معطّل."]})

        account = None
        asset_name = (raw.get("asset_name") or "").strip()
        asset_category = raw.get("asset_category") or ""
        description = (raw.get("description") or "").strip()
        if line_type == SupplierBillLine.LineType.ASSET:
            if not asset_name:
                raise ValidationError({"lines": [f"السطر {index}: اسم الأصل مطلوب لسطر الأصل."]})
            if asset_category not in Asset.Category.values:
                raise ValidationError({"lines": [f"السطر {index}: فئة الأصل مطلوبة لسطر الأصل."]})
        else:
            asset_name, asset_category = "", ""
            if raw.get("account"):
                account = Account.objects.filter(tenant=tenant, id=raw["account"], is_active=True).first()
                if account is None:
                    raise ValidationError({"lines": [f"السطر {index}: الحساب غير موجود."]})
            else:
                account = default_expense
            if account is None:
                raise ValidationError({"lines": [f"السطر {index}: اختر الحساب (لا حساب مصروف افتراضي لهذا المورد)."]})
            if not account.can_post or not account.allow_manual_posting:
                raise ValidationError(
                    {"lines": [f"السطر {index}: لا يمكن تحميل السطر على الحساب {account.code} — حساب رئيسي أو حساب نظام."]}
                )
        lines.append(
            compute_line(
                SupplierBillLine(
                    line_no=index, line_type=line_type, description=description, account=account,
                    cost_center=cost_center, qty=qty, unit_price=unit_price, tax_code=tax_code,
                    vat_deductible=raw.get("vat_deductible", True), wht_code=wht_code,
                    asset_name=asset_name, asset_category=asset_category,
                )
            )
        )
    if not lines:
        raise ValidationError({"lines": ["الفاتورة تحتاج سطرًا واحدًا على الأقل."]})
    return lines


def recalculate_bill(bill, lines):
    bill.subtotal = sum((line.net for line in lines), Decimal("0"))
    bill.capitalized_tax = sum((line.capitalized_tax for line in lines), Decimal("0"))
    bill.reverse_charge_tax = sum(
        (line.tax_amount for line in lines if line.tax_code.kind == TaxCode.Kind.REVERSE_CHARGE), Decimal("0")
    )
    bill.deductible_tax = sum(
        (
            line.tax_amount for line in lines
            if line.tax_code.kind != TaxCode.Kind.REVERSE_CHARGE and is_vat_deductible(line)
        ),
        Decimal("0"),
    )
    bill.total = sum((line.payable for line in lines), Decimal("0"))
    bill.wht_expected = sum((line.wht_amount for line in lines), Decimal("0"))
    bill.base_total = _q(bill.total * bill.exchange_rate)


# -- header -------------------------------------------------------------------


def supplier_role(party):
    from apps.parties.models import PartyRole

    return PartyRole.objects.filter(party=party, role=PartyRole.Role.SUPPLIER, is_active=True).first()


def default_due_date(supplier, on_date):
    from datetime import timedelta

    role = supplier_role(supplier)
    days = (role.details or {}).get("payment_terms_days") if role is not None else None
    if days in (None, ""):
        return None
    return on_date + timedelta(days=int(days))


def _validate_header(tenant, data, bill=None):
    from apps.organization.models import LegalEntity

    supplier = data["supplier"]
    if supplier.tenant_id != tenant.id or supplier_role(supplier) is None:
        raise ValidationError({"supplier": ["الطرف المختار ليس موردًا نشطًا."]})
    if data["legal_entity"].entity_type == LegalEntity.Type.HOLDING:
        raise ValidationError({"legal_entity": ["الشركة القابضة لا تسجّل فواتير موردين — اختر شركة أو فرعًا."]})
    bill_number = (data.get("bill_number") or "").strip()
    if not bill_number:
        raise ValidationError({"bill_number": ["رقم فاتورة المورد مطلوب."]})
    data["bill_number"] = bill_number
    duplicate = SupplierBill.objects.filter(
        tenant=tenant, supplier=supplier, bill_number=bill_number, deleted_at__isnull=True
    )
    if bill is not None:
        duplicate = duplicate.exclude(pk=bill.pk)
    existing = duplicate.first()
    if existing is not None:
        raise ValidationError(
            {
                "bill_number": [
                    f"رقم فاتورة المورد «{bill_number}» مسجَّل من قبل لهذا المورد"
                    f"{' في ' + existing.number if existing.number else ''}."
                ]
            }
        )
    if data.get("due_date") and data["due_date"] < data["date"]:
        raise ValidationError({"due_date": ["تاريخ الاستحقاق قبل تاريخ الفاتورة."]})


_HEADER_FIELDS = (
    "legal_entity", "supplier", "bill_number", "date", "due_date", "currency", "exchange_rate", "reference", "notes",
)


def _write(bill, lines):
    for line in lines:
        line.bill = bill
    SupplierBillLine.objects.bulk_create(lines)
    recalculate_bill(bill, lines)
    bill.save()


@transaction.atomic
def create_supplier_bill(tenant, user, data, raw_lines, request=None):
    _validate_header(tenant, data)
    lines = resolve_bill_lines(tenant, data["supplier"], raw_lines)
    if not data.get("due_date"):
        data["due_date"] = default_due_date(data["supplier"], data["date"])
    bill = SupplierBill(
        tenant=tenant, created_by=user, status=SupplierBill.Status.DRAFT,
        **{name: data[name] for name in _HEADER_FIELDS if name in data},
    )
    bill.save()
    _write(bill, lines)
    _log(user, "created", bill, request=request)
    return bill


@transaction.atomic
def update_supplier_bill(bill, user, data, raw_lines, request=None):
    """Full replace of a DRAFT's header and lines; anything past DRAFT is
    refused (SupplierBillLocked -> 409), whatever the client shows."""
    bill.status = SupplierBill.objects.select_for_update().get(pk=bill.pk).status
    if bill.status != SupplierBill.Status.DRAFT:
        raise SupplierBillLocked("لا تُعدَّل إلا الفاتورة المسودة — هذه الفاتورة مرحَّلة أو قيد الاعتماد.")
    merged = {**{name: getattr(bill, name) for name in _HEADER_FIELDS}, **data}
    _validate_header(bill.tenant, merged, bill=bill)
    if raw_lines is None:
        raw_lines = [
            {
                "line_type": line.line_type, "description": line.description, "account": line.account_id,
                "cost_center": line.cost_center_id, "qty": line.qty, "unit_price": line.unit_price,
                "tax_code": line.tax_code_id, "vat_deductible": line.vat_deductible, "wht_code": line.wht_code_id,
                "asset_name": line.asset_name, "asset_category": line.asset_category,
            }
            for line in bill.lines.all()
        ]
    lines = resolve_bill_lines(bill.tenant, merged["supplier"], raw_lines)
    for name in _HEADER_FIELDS:
        setattr(bill, name, merged.get(name))
    bill.lines.all().delete()
    _write(bill, lines)
    _log(user, "updated", bill, request=request)
    return bill


# -- workflow -------------------------------------------------------------------


@transaction.atomic
def submit_supplier_bill(bill, user, request=None):
    """DRAFT -> PENDING_APPROVAL (or APPROVED when no rule matches). The
    number (PINV) is given here, at the first exit from DRAFT, and kept
    through a rejection. The mandatory-attachment rule is checked inside
    submit_for_approval, the one place every document type checks it."""
    from apps.approvals.services import submit_for_approval
    from apps.numbering.services import next_document_number

    bill = SupplierBill.objects.select_for_update().get(pk=bill.pk)
    if not bill.lines.exists():
        raise ValidationError("لا تُرسَل للاعتماد فاتورة بلا سطور.")
    if not bill.number:
        bill.number = next_document_number(bill.tenant, DOC_TYPE, bill.legal_entity, bill.date)
        bill.save(update_fields=["number"])
    submit_for_approval(bill, user, DOC_TYPE, bill.base_total, request=request)
    return bill


@transaction.atomic
def approve_supplier_bill(bill, user, request=None, emergency_reason=""):
    from apps.approvals.services import approve

    approve(bill, user, DOC_TYPE, bill.base_total, request=request, emergency_reason=emergency_reason)
    return bill


def reject_supplier_bill(bill, user, reason, request=None):
    from apps.approvals.services import reject

    return reject(bill, user, DOC_TYPE, reason, request=request)


def withdraw_supplier_bill(bill, user, request=None):
    from apps.approvals.services import withdraw

    return withdraw(bill, user, DOC_TYPE, request=request)


# -- posting --------------------------------------------------------------------


def _spec(account, debit_fc, credit_fc, bill, cost_center=None, description=""):
    return {
        "account": account, "cost_center": cost_center, "description": description,
        "currency": bill.currency, "exchange_rate": bill.exchange_rate,
        "debit_fc": debit_fc, "credit_fc": credit_fc,
    }


def build_posting_specs(bill):
    """The journal lines of D4 for this bill (see the module docstring)."""
    from apps.accounting.services import (
        check_cost_center_required,
        get_or_create_party_role_account,
        get_required_system_account,
    )
    from apps.parties.models import PartyRole

    tenant = bill.tenant
    zero = Decimal("0")
    specs = []
    deductible_input = zero
    output_rc = zero
    for line in bill.lines.select_related("account", "tax_code", "cost_center"):
        if line.line_type == SupplierBillLine.LineType.ASSET:
            account = get_required_system_account(tenant, "FIXED_ASSETS")
        else:
            account = line.account
            check_cost_center_required(tenant, account, line.cost_center)
        label = line.asset_name or line.description
        specs.append(_spec(account, line.cost, zero, bill, line.cost_center, label))
        if line.tax_code.kind == TaxCode.Kind.REVERSE_CHARGE:
            output_rc += line.tax_amount
        if is_vat_deductible(line):
            deductible_input += line.tax_amount
    if deductible_input:
        specs.append(_spec(get_required_system_account(tenant, "VAT_INPUT"), deductible_input, zero, bill))
    if output_rc:
        specs.append(_spec(get_required_system_account(tenant, "VAT_OUTPUT"), zero, output_rc, bill))
    supplier_account = get_or_create_party_role_account(bill.supplier, PartyRole.Role.SUPPLIER)
    if supplier_account is None:
        raise ValidationError("تعذّر تحديد حساب المورد — حساب الموردين (النظام) غير موجود.")
    specs.append(_spec(supplier_account, zero, bill.total, bill, description=bill.bill_number))
    return specs


def _asset_code(bill, line):
    from apps.assets.models import Asset

    code = f"FA-{bill.number.removeprefix('PINV-')}-{line.line_no}"
    if len(code) > 20 or Asset.objects.filter(tenant=bill.tenant, code=code).exists():
        code = f"FA-{line.id.hex[:10]}"
    return code


def _create_asset(bill, line, user, request=None):
    """R-8.7, as built: the asset is ACTIVE (Asset has no draft status, and
    the ledger already holds the debit on FIXED_ASSETS), with
    purchase_cost = the line's cost (net + any capitalized VAT),
    purchase_reference = the bill's number, purchase_date = its date, and
    no in_service_date — depreciation is refused until one is set on the
    asset's own screen (apps.assets.depreciation.start_depreciation)."""
    from apps.assets.models import Asset

    asset = Asset.objects.create(
        tenant=bill.tenant, legal_entity=bill.legal_entity, code=_asset_code(bill, line), name=line.asset_name,
        category=line.asset_category, purchase_date=bill.date, purchase_cost=line.cost, currency=bill.currency,
        purchase_reference=bill.number, cost_center=line.cost_center, in_service_date=None,
    )
    line.asset = asset
    line.save(update_fields=["asset"])
    log_action(
        actor_type=AuditLog.ActorType.TENANT_USER, actor_id=user.id, action="assets.asset.created",
        target_type="assets.asset", target_id=asset.id, tenant_id=bill.tenant_id,
        after={"source": "supplier_bill", "bill": bill.number, "line": line.line_no}, request=request,
    )
    return asset


@transaction.atomic
def post_supplier_bill(bill, user, request=None):
    from django.contrib.contenttypes.models import ContentType

    from apps.accounting.models import JournalEntry, JournalLine
    from apps.accounting.periods import assert_open_period
    from apps.accounting.services import build_journal_lines_with_fx_rounding
    from apps.numbering.services import next_document_number

    bill = SupplierBill.objects.select_for_update().select_related("supplier", "legal_entity").get(pk=bill.pk)
    if bill.status != SupplierBill.Status.APPROVED:
        raise ValidationError("لا تُرحَّل إلا الفاتورة المعتمدة.")
    assert_open_period(bill.tenant, bill.date)
    specs = build_posting_specs(bill)
    entry = JournalEntry.objects.create(
        tenant=bill.tenant, legal_entity=bill.legal_entity, date=bill.date,
        memo=f"فاتورة مورد {bill.number} — {bill.supplier.name} ({bill.bill_number})", reference=bill.bill_number,
        number=next_document_number(bill.tenant, "journal_entry", bill.legal_entity, bill.date),
        status=JournalEntry.Status.POSTED, produced_by=JournalEntry.ProducedBy.SUPPLIER_BILL,
        content_type=ContentType.objects.get_for_model(SupplierBill), object_id=bill.id,
        currency=bill.currency, exchange_rate=bill.exchange_rate, created_by=user,
    )
    JournalLine.objects.bulk_create(build_journal_lines_with_fx_rounding(bill.tenant, entry, specs, bill.exchange_rate))
    for line in bill.lines.filter(line_type=SupplierBillLine.LineType.ASSET).order_by("line_no"):
        _create_asset(bill, line, user, request=request)
    bill.status = SupplierBill.Status.POSTED
    bill.journal_entry = entry
    bill.posted_at = timezone.now()
    bill.save(update_fields=["status", "journal_entry", "posted_at"])
    _log(user, "posted", bill, request=request, after={"journal_entry": entry.number})
    return bill


def _asset_blocks_reversal(asset):
    """An asset the bill created can be withdrawn with it only while
    nothing has happened to it since."""
    if asset.depreciation_entry_id:
        return "بدأ إهلاكه"
    if asset.additions.exists():
        return "عليه إضافات رأسمالية"
    if asset.disposals.exists():
        return "عليه استبعاد"
    if asset.transfers.exists():
        return "نُقل بين الفروع"
    return None


@transaction.atomic
def reverse_supplier_bill(bill, user, reason, request=None):
    """A full mirror entry (apps.accounting.services.reverse_journal_entry).
    An asset the bill created is soft-deleted with it — refused if the
    asset has a life of its own by now (depreciation, additions, disposal,
    transfer): the ledger and the register must not part ways."""
    from apps.accounting.services import reverse_journal_entry

    bill = SupplierBill.objects.select_for_update().get(pk=bill.pk)
    if bill.status != SupplierBill.Status.POSTED:
        raise ValidationError("لا تُعكس إلا الفاتورة المرحَّلة.")
    if not (reason or "").strip():
        raise ValidationError("سبب العكس مطلوب.")
    assets = [line.asset for line in bill.lines.filter(asset__isnull=False).select_related("asset")]
    for asset in assets:
        blocker = _asset_blocks_reversal(asset)
        if blocker:
            raise ValidationError(
                f"لا تُعكس الفاتورة: الأصل {asset.code} «{asset.name}» الذي أنشأته {blocker}."
            )
    reverse_journal_entry(bill.journal_entry, user, reason)
    now = timezone.now()
    for asset in assets:
        asset.deleted_at = now
        asset.deleted_by = user
        asset.is_active = False
        asset.save(update_fields=["deleted_at", "deleted_by", "is_active"])
    bill.status = SupplierBill.Status.REVERSED
    bill.save(update_fields=["status"])
    _log(user, "reversed", bill, request=request, after={"reason": reason})
    return bill
