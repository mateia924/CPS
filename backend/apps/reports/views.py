import datetime as dt

from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access.services import user_has_permission
from apps.organization.models import CostCenter, LegalEntity
from apps.organization.services import get_accessible_entity_ids

from .services import aging_report, balance_sheet, fixed_assets_register, income_statement


def _require_accounting_view(request):
    # Sprint 6.6: these are plain APIViews, not ViewSets — HasModule
    # Permission (apps.access.permissions) reads `view.action`, a
    # DRF ViewSet-only concept, and would crash here (see the sibling
    # DashboardSummaryView/PendingApprovalsView precedent, which sidestep
    # this the other way by not gating at all — financial statements
    # warrant an actual RBAC check, so this checks directly instead).
    if not user_has_permission(request.user, "accounting.view"):
        raise PermissionDenied()


def _money_rows(rows):
    out = []
    for row in rows:
        converted = {**row, "amount": str(row["amount"])}
        if "lines" in converted:
            converted["lines"] = [{**line, "amount": str(line["amount"])} for line in converted["lines"]]
        out.append(converted)
    return out


def _resolve_legal_entity(request):
    entity_id = request.query_params.get("legal_entity")
    if not entity_id:
        return None
    accessible_ids = get_accessible_entity_ids(request.user)
    try:
        return LegalEntity.objects.get(tenant=request.user.tenant, id__in=accessible_ids, id=entity_id)
    except LegalEntity.DoesNotExist:
        raise ValidationError({"legal_entity": ["Legal entity not found."]})


def _resolve_cost_center(request):
    cost_center_id = request.query_params.get("cost_center")
    if not cost_center_id:
        return None
    try:
        return CostCenter.objects.get(tenant=request.user.tenant, id=cost_center_id)
    except CostCenter.DoesNotExist:
        raise ValidationError({"cost_center": ["Cost center not found."]})


def _parse_date(request, key):
    value = request.query_params.get(key)
    if not value:
        return None
    return dt.date.fromisoformat(value)


def _report_envelope(request, legal_entity, data):

    if legal_entity is not None:
        base_currency = legal_entity.base_currency
    else:
        first_entity = LegalEntity.objects.filter(tenant=request.user.tenant).order_by("code").first()
        base_currency = first_entity.base_currency if first_entity else "SAR"
    data["generated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    data["prepared_by"] = request.user.get_full_name() or request.user.email
    data["base_currency"] = base_currency
    return data


class IncomeStatementView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        _require_accounting_view(request)
        legal_entity = _resolve_legal_entity(request)
        cost_center = _resolve_cost_center(request)
        include_children = request.query_params.get("include_children", "true") != "false"
        date_from = _parse_date(request, "from")
        date_to = _parse_date(request, "to")

        result = income_statement(
            request.user.tenant, legal_entity, include_children, date_from, date_to, cost_center
        )
        payload = {
            "revenue": _money_rows(result["revenue"]),
            "expense": _money_rows(result["expense"]),
            "total_revenue": str(result["total_revenue"]),
            "total_expense": str(result["total_expense"]),
            "net_income": str(result["net_income"]),
        }
        return Response(_report_envelope(request, legal_entity, payload))


class BalanceSheetView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        _require_accounting_view(request)
        legal_entity = _resolve_legal_entity(request)
        cost_center = _resolve_cost_center(request)
        include_children = request.query_params.get("include_children", "true") != "false"
        as_of = _parse_date(request, "as_of")

        result = balance_sheet(request.user.tenant, legal_entity, include_children, as_of, cost_center)
        payload = {
            "assets": _money_rows(result["assets"]),
            "liabilities": _money_rows(result["liabilities"]),
            "equity": _money_rows(result["equity"]),
            "total_assets": str(result["total_assets"]),
            "total_liabilities": str(result["total_liabilities"]),
            "total_equity": str(result["total_equity"]),
            "check": {"balanced": result["check"]["balanced"], "difference": str(result["check"]["difference"])},
            "as_of": result["as_of"],
        }
        return Response(_report_envelope(request, legal_entity, payload))


class AgingReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        _require_accounting_view(request)
        legal_entity = _resolve_legal_entity(request)
        as_of = _parse_date(request, "as_of")

        result = aging_report(request.user.tenant, legal_entity, as_of)
        payload = {
            "rows": [{**row, "amount_base": str(row["amount_base"])} for row in result["rows"]],
            "totals_by_party": [{**row, "amount_base": str(row["amount_base"])} for row in result["totals_by_party"]],
            "total": str(result["total"]),
            "as_of": result["as_of"],
        }
        return Response(_report_envelope(request, legal_entity, payload))


class FixedAssetsRegisterView(APIView):
    """Sprint 6.5 (decision 13): "سجل الأصول الثابتة"."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        _require_accounting_view(request)
        legal_entity = _resolve_legal_entity(request)
        include_children = request.query_params.get("include_children", "true") != "false"
        as_of = _parse_date(request, "as_of")

        result = fixed_assets_register(request.user.tenant, as_of=as_of, legal_entity=legal_entity, include_children=include_children)
        row_money_fields = ("cost", "additions", "disposals", "accumulated_depreciation", "book_value")
        payload = {
            "rows": [
                {**row, **{field: str(row[field]) for field in row_money_fields}} for row in result["rows"]
            ],
            "totals": {key: str(value) for key, value in result["totals"].items()},
            "reconciliation": {key: str(value) for key, value in result["reconciliation"].items()},
            "as_of": result["as_of"],
        }
        return Response(_report_envelope(request, legal_entity, payload))
