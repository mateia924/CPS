"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { Money } from "@/components/Money";
import { formatDateTime } from "@/lib/date";
import { useLocale } from "@/lib/i18n";
import type { AgingReport, LegalEntity, Paginated } from "@/lib/types";

function AgingPrint() {
  const { t } = useLocale();
  const searchParams = useSearchParams();
  const legalEntityId = searchParams.get("legal_entity") || "";
  const asOf = searchParams.get("as_of") || "";

  const [entity, setEntity] = useState<LegalEntity | null>(null);
  const [report, setReport] = useState<AgingReport | null>(null);

  useEffect(() => {
    api.get<Paginated<LegalEntity>>("/legal-entities/").then((data) => setEntity(data.results[0] || null));
    const params = new URLSearchParams();
    if (legalEntityId) params.set("legal_entity", legalEntityId);
    if (asOf) params.set("as_of", asOf);
    api.get<AgingReport>(`/reports/aging/?${params.toString()}`).then(setReport);
  }, [legalEntityId, asOf]);

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
            <h2>{t("agingReportNav")}</h2>
            <p>{t("asOf")}: {report.as_of}</p>
            <p>{t("preparedBy")}: {report.prepared_by}</p>
            <p>{formatDateTime(report.generated_at, "form")}</p>
          </div>
        </div>

        <hr style={{ margin: "1.5rem 0", border: "none", borderTop: "1px solid var(--border)" }} />

        <table>
          <thead>
            <tr>
              <th>{t("customer")}</th>
              <th>{t("source")}</th>
              <th>{t("reference")}</th>
              <th>{t("dueDate")}</th>
              <th>{t("amount")}</th>
              <th>{t("bucket")}</th>
            </tr>
          </thead>
          <tbody>
            {report.rows.map((row, i) => (
              <tr key={i}>
                <td>{row.party_name}</td>
                <td>{row.is_opening ? t("openingBalanceSource") : t("invoiceSource")}</td>
                <td>{row.reference}</td>
                <td>{row.due_date}</td>
                <td><Money amount={row.amount_base} /></td>
                <td>{row.bucket}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p style={{ marginTop: "1rem", fontSize: "1.1rem" }}>
          <strong>{t("total")}: <Money amount={report.total} /></strong>
        </p>

        <div className="print-signatures">
          <div>{t("signatureAccountant")}</div>
          <div>{t("signatureManager")}</div>
        </div>
      </div>
    </div>
  );
}

export default function AgingPrintPage() {
  return (
    <Suspense fallback={null}>
      <AgingPrint />
    </Suspense>
  );
}
