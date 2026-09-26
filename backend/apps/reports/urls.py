from django.urls import path

from .views import AgingReportView, BalanceSheetView, FixedAssetsRegisterView, IncomeStatementView

urlpatterns = [
    path("reports/income-statement/", IncomeStatementView.as_view(), name="report-income-statement"),
    path("reports/balance-sheet/", BalanceSheetView.as_view(), name="report-balance-sheet"),
    path("reports/aging/", AgingReportView.as_view(), name="report-aging"),
    path("reports/fixed-assets/", FixedAssetsRegisterView.as_view(), name="report-fixed-assets"),
]
