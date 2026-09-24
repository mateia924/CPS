"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Money } from "@/components/Money";
import { useLocale } from "@/lib/i18n";
import type { AgingReport, LegalEntity, Paginated } from "@/lib/types";

export default function AgingReportPage() {
  const { t } = useLocale();
  const [entities, setEntities] = useState<LegalEntity[]>([]);
  const [legalEntityId, setLegalEntityId] = useState("");
  const [asOf, setAsOf] = useState(() => new Date().toISOString().slice(0, 10));
  const [result, setResult] = useState<AgingReport | null>(null);

  useEffect(() => {
    api.get<Paginated<LegalEntity>>("/legal-entities/").then((data) =>
      setEntities(data.results.filter((entity) => entity.entity_type !== "holding"))
    );
  }, []);

  const load = async () => {
    const params = new URLSearchParams();
    if (legalEntityId) params.set("legal_entity", legalEntityId);
    if (asOf) params.set("as_of", asOf);
    const data = await api.get<AgingReport>(`/reports/aging/?${params.toString()}`);
    setResult(data);
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div>
      <h1>{t("agingReportNav")}</h1>

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
            <label>{t("asOf")}</label>
            <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
          </div>
          <button className="primary" onClick={load}>{t("submit")}</button>
        </div>
      </div>

      {result && (
        <div className="card">
          <h3>{t("byParty")}</h3>
          <table>
            <thead>
              <tr>
                <th>{t("customer")}</th>
                <th>{t("agingTotal")}</th>
              </tr>
            </thead>
            <tbody>
              {result.totals_by_party.map((row) => (
                <tr key={row.party_id}>
                  <td>{row.party_name}</td>
                  <td><Money amount={row.amount_base} /></td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3 style={{ marginTop: "1rem" }}>{t("details")}</h3>
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
              {result.rows.map((row, i) => (
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
          <p><strong>{t("total")}: <Money amount={result.total} /></strong></p>

          <a
            href={`/print/reports/aging?${new URLSearchParams({
              ...(legalEntityId ? { legal_entity: legalEntityId } : {}),
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
