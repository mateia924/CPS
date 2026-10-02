"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { Money } from "@/components/Money";
import { formatDateTime } from "@/lib/date";
import { useAuth } from "@/lib/auth-context";
import { useLocale } from "@/lib/i18n";
import type { IncomeStatementReport, LegalEntity, Paginated } from "@/lib/types";

function IncomeStatementPrint() {
  const { t } = useLocale();
  const { user } = useAuth();
  const searchParams = useSearchParams();
  const legalEntityId = searchParams.get("legal_entity") || "";
  const includeChildren = searchParams.get("include_children") !== "false";
  const dateFrom = searchParams.get("from") || "";
  const dateTo = searchParams.get("to") || "";

  const [entity, setEntity] = useState<LegalEntity | null>(null);
  const [report, setReport] = useState<IncomeStatementReport | null>(null);

  useEffect(() => {
    api.get<Paginated<LegalEntity>>("/legal-entities/").then((data) => setEntity(data.results[0] || null));
    const params = new URLSearchParams({ include_children: String(includeChildren) });
    if (legalEntityId) params.set("legal_entity", legalEntityId);
    if (dateFrom) params.set("from", dateFrom);
    if (dateTo) params.set("to", dateTo);
    api.get<IncomeStatementReport>(`/reports/income-statement/?${params.toString()}`).then(setReport);
  }, [legalEntityId, includeChildren, dateFrom, dateTo]);

  if (!report || !entity) return null;

  return (
    <div>
      <div className="print-actions">
        <button className="primary" onClick={() => window.print()}>{t("printButton")}</button>
      </div>
      <div className="print-page">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
          <div style={{ display: "flex", gap: "0.75rem", alignItems: "start" }}>
            <img src="/brand/cps-logo-horizontal.svg" alt="CPS" style={{ height: 48 }} />
            <div><h2 style={{ margin: 0 }}>{entity.name}</h2></div>
          </div>
          <div style={{ textAlign: "end" }}>
            <h2>{t("incomeStatementNav")}</h2>
            {(dateFrom || dateTo) && <p>{t("dateFrom")}: {dateFrom || "—"} — {t("dateTo")}: {dateTo || "—"}</p>}
            <p>{t("preparedBy")}: {report.prepared_by}</p>
            <p>{formatDateTime(report.generated_at, "form")}</p>
          </div>
        </div>

        <hr style={{ margin: "1.5rem 0", border: "none", borderTop: "1px solid var(--border)" }} />

        <h3>{t("revenueType")}</h3>
        <table>
          <tbody>
            {report.revenue.map((row) => (
              <tr key={row.account_id}><td>{row.code} — {row.name}</td><td><Money amount={row.amount} /></td></tr>
            ))}
          </tbody>
        </table>
        <p><strong>{t("total")}: <Money amount={report.total_revenue} /></strong></p>

        <h3 style={{ marginTop: "1rem" }}>{t("expenseType")}</h3>
        <table>
          <tbody>
            {report.expense.map((row) => (
              <tr key={row.account_id}><td>{row.code} — {row.name}</td><td><Money amount={row.amount} /></td></tr>
            ))}
          </tbody>
        </table>
        <p><strong>{t("total")}: <Money amount={report.total_expense} /></strong></p>

        <p style={{ marginTop: "1rem", fontSize: "1.1rem" }}>
          <strong>{t("netIncome")}: <Money amount={report.net_income} /></strong>
        </p>

        <div className="print-signatures">
          <div>{t("signatureAccountant")}</div>
          <div>{t("signatureManager")}</div>
        </div>
      </div>
    </div>
  );
}

export default function IncomeStatementPrintPage() {
  return (
    <Suspense fallback={null}>
      <IncomeStatementPrint />
    </Suspense>
  );
}
