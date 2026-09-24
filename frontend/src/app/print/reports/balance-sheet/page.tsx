"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { Money } from "@/components/Money";
import { useLocale } from "@/lib/i18n";
import type { BalanceSheetReport, LegalEntity, Paginated } from "@/lib/types";

function BalanceSheetPrint() {
  const { t } = useLocale();
  const searchParams = useSearchParams();
  const legalEntityId = searchParams.get("legal_entity") || "";
  const includeChildren = searchParams.get("include_children") !== "false";
  const asOf = searchParams.get("as_of") || "";

  const [entity, setEntity] = useState<LegalEntity | null>(null);
  const [report, setReport] = useState<BalanceSheetReport | null>(null);

  useEffect(() => {
    api.get<Paginated<LegalEntity>>("/legal-entities/").then((data) => setEntity(data.results[0] || null));
    const params = new URLSearchParams({ include_children: String(includeChildren) });
    if (legalEntityId) params.set("legal_entity", legalEntityId);
    if (asOf) params.set("as_of", asOf);
    api.get<BalanceSheetReport>(`/reports/balance-sheet/?${params.toString()}`).then(setReport);
  }, [legalEntityId, includeChildren, asOf]);

  if (!report || !entity) return null;

  const section = (title: string, rows: BalanceSheetReport["assets"], total: string) => (
    <>
      <h3 style={{ marginTop: "1rem" }}>{title}</h3>
      <table>
        <tbody>
          {rows.map((row) => (
            <tr key={row.account_id ?? row.name}>
              <td>{row.code ? `${row.code} — ${row.name}` : row.name}</td>
              <td><Money amount={row.amount} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      <p><strong>{t("total")}: <Money amount={total} /></strong></p>
    </>
  );

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
            <h2>{t("balanceSheetNav")}</h2>
            <p>{t("asOf")}: {report.as_of}</p>
            <p>{t("preparedBy")}: {report.prepared_by}</p>
            <p>{new Date(report.generated_at).toLocaleString()}</p>
          </div>
        </div>

        <hr style={{ margin: "1.5rem 0", border: "none", borderTop: "1px solid var(--border)" }} />

        {section(t("assetType"), report.assets, report.total_assets)}
        {section(t("liabilityType"), report.liabilities, report.total_liabilities)}
        {section(t("equityType"), report.equity, report.total_equity)}

        <div className="print-signatures">
          <div>{t("signatureAccountant")}</div>
          <div>{t("signatureManager")}</div>
        </div>
      </div>
    </div>
  );
}

export default function BalanceSheetPrintPage() {
  return (
    <Suspense fallback={null}>
      <BalanceSheetPrint />
    </Suspense>
  );
}
