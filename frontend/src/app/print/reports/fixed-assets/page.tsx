"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { Money } from "@/components/Money";
import { formatDateTime } from "@/lib/date";
import { useLocale } from "@/lib/i18n";
import type { FixedAssetRegisterReport, LegalEntity, Paginated } from "@/lib/types";

function FixedAssetsPrint() {
  const { t } = useLocale();
  const searchParams = useSearchParams();
  const legalEntityId = searchParams.get("legal_entity") || "";
  const includeChildren = searchParams.get("include_children") !== "false";
  const asOf = searchParams.get("as_of") || "";

  const [entity, setEntity] = useState<LegalEntity | null>(null);
  const [report, setReport] = useState<FixedAssetRegisterReport | null>(null);

  useEffect(() => {
    api.get<Paginated<LegalEntity>>("/legal-entities/").then((data) => setEntity(data.results[0] || null));
    const params = new URLSearchParams({ include_children: String(includeChildren) });
    if (legalEntityId) params.set("legal_entity", legalEntityId);
    if (asOf) params.set("as_of", asOf);
    api.get<FixedAssetRegisterReport>(`/reports/fixed-assets/?${params.toString()}`).then(setReport);
  }, [legalEntityId, includeChildren, asOf]);

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
            <h2>{t("fixedAssetsReportNav")}</h2>
            <p>{t("asOf")}: {report.as_of}</p>
            <p>{t("preparedBy")}: {report.prepared_by}</p>
            <p>{formatDateTime(report.generated_at, "form")}</p>
          </div>
        </div>

        <hr style={{ margin: "1.5rem 0", border: "none", borderTop: "1px solid var(--border)" }} />

        <table>
          <thead>
            <tr>
              <th>{t("code")}</th>
              <th>{t("name")}</th>
              <th>{t("purchaseCost")}</th>
              <th>{t("addAddition")}</th>
              <th>{t("disposeAsset")}</th>
              <th>{t("accumulatedDepreciationCard")}</th>
              <th>{t("bookValueCard")}</th>
              <th>{t("remainingMonths")}</th>
            </tr>
          </thead>
          <tbody>
            {report.rows.map((row) => (
              <tr key={row.asset_id}>
                <td>{row.code}</td>
                <td>{row.name}</td>
                <td><Money amount={row.cost} /></td>
                <td><Money amount={row.additions} /></td>
                <td><Money amount={row.disposals} /></td>
                <td><Money amount={row.accumulated_depreciation} /></td>
                <td><Money amount={row.book_value} /></td>
                <td>{row.remaining_months}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td colSpan={2}><strong>{t("total")}</strong></td>
              <td><strong><Money amount={report.totals.cost} /></strong></td>
              <td><strong><Money amount={report.totals.additions} /></strong></td>
              <td><strong><Money amount={report.totals.disposals} /></strong></td>
              <td><strong><Money amount={report.totals.accumulated_depreciation} /></strong></td>
              <td><strong><Money amount={report.totals.book_value} /></strong></td>
              <td></td>
            </tr>
          </tfoot>
        </table>

        <h3 style={{ marginTop: "1rem" }}>{t("reconciliation")}</h3>
        <table>
          <thead>
            <tr>
              <th></th>
              <th>{t("registerTotal")}</th>
              <th>{t("ledgerTotal")}</th>
              <th>{t("difference")}</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>{t("purchaseCost")}</td>
              <td><Money amount={report.reconciliation.register_cost} /></td>
              <td><Money amount={report.reconciliation.ledger_cost} /></td>
              <td><Money amount={report.reconciliation.cost_diff} /></td>
            </tr>
            <tr>
              <td>{t("accumulatedDepreciationCard")}</td>
              <td><Money amount={report.reconciliation.register_accumulated_depreciation} /></td>
              <td><Money amount={report.reconciliation.ledger_accumulated_depreciation} /></td>
              <td><Money amount={report.reconciliation.accum_diff} /></td>
            </tr>
          </tbody>
        </table>

        <div className="print-signatures">
          <div>{t("signatureAccountant")}</div>
          <div>{t("signatureManager")}</div>
        </div>
      </div>
    </div>
  );
}

export default function FixedAssetsPrintPage() {
  return (
    <Suspense fallback={null}>
      <FixedAssetsPrint />
    </Suspense>
  );
}
