"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { Money } from "@/components/Money";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import type { DashboardSummary } from "@/lib/types";

const PERIOD_STATUS_LABEL_KEY: Record<string, string> = {
  open: "periodOpen",
  closed: "periodClosed",
  locked: "periodLocked",
};

// 3.18 row 1 ("لوحة التحكم"): four cards backed by one endpoint
// (sprint 6.0.1-B) instead of the ad-hoc per-currency cash query this
// page used to run client-side on its own.
export default function DashboardHome() {
  const { user, tenant } = useAuth();
  const { t } = useLocale();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);

  useEffect(() => {
    api.get<DashboardSummary>("/dashboard/summary/").then(setSummary);
  }, []);

  const cashEntries = summary ? Object.entries(summary.cash) : [];
  const hasAlerts =
    summary &&
    (summary.overdue_invoices.count > 0 ||
      summary.pending_approvals > 0 ||
      summary.due_recurring_installments > 0 ||
      summary.fiscal_year_ending_soon !== null ||
      summary.opening_not_approved.length > 0);

  return (
    <div>
      <div className="card">
        <h1>
          {t("welcome")}, {user?.first_name || user?.email}
        </h1>
        <p>{tenant?.name}</p>
      </div>

      {summary && (
        <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
          <div className="card" style={{ flex: "1 1 220px" }}>
            <h3>{t("cashOnHandCard")}</h3>
            {cashEntries.length === 0 ? (
              <p style={{ color: "var(--muted)" }}>{t("noData")}</p>
            ) : (
              cashEntries.map(([currency, amount]) => (
                <p key={currency} style={{ fontSize: "1.4rem", margin: "0.2rem 0" }}>
                  <Money amount={amount} currency={currency} />
                </p>
              ))
            )}
          </div>

          <div className="card" style={{ flex: "1 1 220px" }}>
            <h3>{t("receivablesOpenCard")}</h3>
            <p style={{ fontSize: "1.4rem", margin: "0.2rem 0" }}>
              <Money amount={summary.receivables_open} />
            </p>
          </div>

          <div className="card" style={{ flex: "1 1 220px" }}>
            <h3>{t("salesMonthCard")}</h3>
            <p style={{ fontSize: "1.4rem", margin: "0.2rem 0" }}>
              <Money amount={summary.sales_month} />
            </p>
          </div>

          <div className="card" style={{ flex: "1 1 220px" }}>
            <h3>{t("currentPeriodCard")}</h3>
            {summary.current_period ? (
              <>
                <p style={{ fontSize: "1.2rem", margin: "0.2rem 0" }}>
                  {summary.current_period.fiscal_year_name} — {t("periodSeqLabel")} {summary.current_period.seq}
                </p>
                <p style={{ color: "var(--muted)" }}>
                  {t(PERIOD_STATUS_LABEL_KEY[summary.current_period.status] ?? "periodOpen")}
                </p>
              </>
            ) : (
              <p style={{ color: "var(--muted)" }}>{t("noData")}</p>
            )}
            <Link href="/dashboard/settings/fiscal-years">{t("fiscalYearsNav")}</Link>
          </div>

          <div className="card" style={{ flex: "1 1 220px" }}>
            <h3>{t("alertsCard")}</h3>
            {!hasAlerts ? (
              <p style={{ color: "var(--muted)" }}>{t("noAlerts")}</p>
            ) : (
              <>
                {summary.overdue_invoices.count > 0 && (
                  <p>
                    <Link href="/dashboard/invoices">
                      {t("overdueInvoicesAlert")}: {summary.overdue_invoices.count} (
                      <Money amount={summary.overdue_invoices.amount} />)
                    </Link>
                  </p>
                )}
                {summary.pending_approvals > 0 && (
                  <p>
                    <Link href="/dashboard/approvals">
                      {t("pendingApprovalsAlert")}: {summary.pending_approvals}
                    </Link>
                  </p>
                )}
                {summary.due_recurring_installments > 0 && (
                  <p>
                    <Link href="/dashboard/accounting/recurring-entries">
                      {t("dueRecurringInstallmentsAlert")}: {summary.due_recurring_installments}
                    </Link>
                  </p>
                )}
                {summary.fiscal_year_ending_soon && (
                  <p>
                    <Link href="/dashboard/settings/fiscal-years">
                      {summary.fiscal_year_ending_soon.next_year_created
                        ? t("fiscalYearAutoCreatedAlert")
                        : `${t("fiscalYearEndingSoonAlert")}: ${summary.fiscal_year_ending_soon.days_left}`}
                    </Link>
                  </p>
                )}
                {summary.opening_not_approved.length > 0 && (
                  <p>
                    <Link href="/dashboard/accounting/opening-balances">
                      {t("openingNotApprovedAlert")}: {summary.opening_not_approved.join("، ")}
                    </Link>
                  </p>
                )}
              </>
            )}
            <p style={{ color: "var(--muted)", fontSize: "0.85rem", marginTop: "0.5rem" }}>
              {t("payablesComingSprint8")}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
