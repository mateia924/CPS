"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Money } from "@/components/Money";
import { useLocale } from "@/lib/i18n";
import type { FixedAssetRegisterReport, LegalEntity, Paginated } from "@/lib/types";

export default function FixedAssetsReportPage() {
  const { t } = useLocale();
  const [entities, setEntities] = useState<LegalEntity[]>([]);
  const [legalEntityId, setLegalEntityId] = useState("");
  const [includeChildren, setIncludeChildren] = useState(true);
  const [asOf, setAsOf] = useState(() => new Date().toISOString().slice(0, 10));
  const [result, setResult] = useState<FixedAssetRegisterReport | null>(null);

  useEffect(() => {
    api.get<Paginated<LegalEntity>>("/legal-entities/").then((data) =>
      setEntities(data.results.filter((entity) => entity.entity_type !== "holding"))
    );
  }, []);

  const load = async () => {
    const params = new URLSearchParams();
    if (legalEntityId) params.set("legal_entity", legalEntityId);
    params.set("include_children", String(includeChildren));
    if (asOf) params.set("as_of", asOf);
    const data = await api.get<FixedAssetRegisterReport>(`/reports/fixed-assets/?${params.toString()}`);
    setResult(data);
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div>
      <h1>{t("fixedAssetsReportNav")}</h1>

      <div className="card">
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "end" }}>
          <div className="form-field">
            <label>{t("legalEntity")}</label>
            <select value={legalEntityId} onChange={(e) => setLegalEntityId(e.target.value)}>
              <option value="">{t("all")}</option>
              {entities.map((entity) => (
                <option key={entity.id} value={entity.id}>{entity.code} — {entity.name}</option>
              ))}
            </select>
          </div>
          <div className="form-field">
            <label>
              <input type="checkbox" checked={includeChildren} onChange={(e) => setIncludeChildren(e.target.checked)} />{" "}
              {t("includeChildren")}
            </label>
          </div>
          <div className="form-field">
            <label>{t("asOf")}</label>
            <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
          </div>
          <button className="primary" onClick={load}>{t("submit")}</button>
        </div>
      </div>

      {result && (
        <div className="card">
          <table>
            <thead>
              <tr>
                <th>{t("code")}</th>
                <th>{t("name")}</th>
                <th>{t("category")}</th>
                <th>{t("depreciationMethod")}</th>
                <th>{t("purchaseCost")}</th>
                <th>{t("addAddition")}</th>
                <th>{t("disposeAsset")}</th>
                <th>{t("accumulatedDepreciationCard")}</th>
                <th>{t("bookValueCard")}</th>
                <th>{t("remainingMonths")}</th>
                <th>{t("assetStatus")}</th>
              </tr>
            </thead>
            <tbody>
              {result.rows.map((row) => (
                <tr key={row.asset_id}>
                  <td>{row.code}</td>
                  <td>{row.name}</td>
                  <td>{t(row.category)}</td>
                  <td>{t(row.depreciation_method === "declining_balance" ? "decliningBalance" : "straightLine")}</td>
                  <td><Money amount={row.cost} /></td>
                  <td><Money amount={row.additions} /></td>
                  <td><Money amount={row.disposals} /></td>
                  <td><Money amount={row.accumulated_depreciation} /></td>
                  <td><Money amount={row.book_value} /></td>
                  <td>{row.remaining_months}</td>
                  <td>{t(row.status === "under_maintenance" ? "underMaintenance" : row.status === "disposed" ? "disposed" : "active")}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={4}><strong>{t("total")}</strong></td>
                <td><strong><Money amount={result.totals.cost} /></strong></td>
                <td><strong><Money amount={result.totals.additions} /></strong></td>
                <td><strong><Money amount={result.totals.disposals} /></strong></td>
                <td><strong><Money amount={result.totals.accumulated_depreciation} /></strong></td>
                <td><strong><Money amount={result.totals.book_value} /></strong></td>
                <td colSpan={2}></td>
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
                <td><Money amount={result.reconciliation.register_cost} /></td>
                <td><Money amount={result.reconciliation.ledger_cost} /></td>
                <td>
                  <strong style={result.reconciliation.cost_diff !== "0.00" ? { color: "var(--danger)" } : undefined}>
                    <Money amount={result.reconciliation.cost_diff} />
                  </strong>
                </td>
              </tr>
              <tr>
                <td>{t("accumulatedDepreciationCard")}</td>
                <td><Money amount={result.reconciliation.register_accumulated_depreciation} /></td>
                <td><Money amount={result.reconciliation.ledger_accumulated_depreciation} /></td>
                <td>
                  <strong style={result.reconciliation.accum_diff !== "0.00" ? { color: "var(--danger)" } : undefined}>
                    <Money amount={result.reconciliation.accum_diff} />
                  </strong>
                </td>
              </tr>
            </tbody>
          </table>

          <a
            href={`/print/reports/fixed-assets?${new URLSearchParams({
              ...(legalEntityId ? { legal_entity: legalEntityId } : {}),
              include_children: String(includeChildren),
              as_of: asOf,
            }).toString()}`}
            target="_blank"
            rel="noreferrer"
          >
            {t("printButton")}
          </a>
        </div>
      )}
    </div>
  );
}
