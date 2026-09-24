"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Money } from "@/components/Money";
import { useLocale } from "@/lib/i18n";
import type { BalanceSheetReport, LegalEntity, Paginated } from "@/lib/types";

export default function BalanceSheetPage() {
  const { t } = useLocale();
  const [entities, setEntities] = useState<LegalEntity[]>([]);
  const [legalEntityId, setLegalEntityId] = useState("");
  const [includeChildren, setIncludeChildren] = useState(true);
  const [asOf, setAsOf] = useState(() => new Date().toISOString().slice(0, 10));
  const [result, setResult] = useState<BalanceSheetReport | null>(null);

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
    const data = await api.get<BalanceSheetReport>(`/reports/balance-sheet/?${params.toString()}`);
    setResult(data);
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
      <h1>{t("balanceSheetNav")}</h1>

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
          {section(t("assetType"), result.assets, result.total_assets)}
          {section(t("liabilityType"), result.liabilities, result.total_liabilities)}
          {section(t("equityType"), result.equity, result.total_equity)}

          <a
            href={`/print/reports/balance-sheet?${new URLSearchParams({
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
