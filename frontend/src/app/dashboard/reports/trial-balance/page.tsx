"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Money } from "@/components/Money";
import { useLocale } from "@/lib/i18n";
import type { LegalEntity, Paginated } from "@/lib/types";

interface TrialBalanceRow {
  account_id: string;
  account_code: string;
  account_name: string;
  debit: string;
  credit: string;
  balance: string;
}

interface TrialBalanceResponse {
  rows: TrialBalanceRow[];
  total_debit: string;
  total_credit: string;
}

export default function TrialBalancePage() {
  const { t } = useLocale();
  const [entities, setEntities] = useState<LegalEntity[]>([]);
  const [legalEntityId, setLegalEntityId] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [result, setResult] = useState<TrialBalanceResponse | null>(null);

  useEffect(() => {
    api.get<Paginated<LegalEntity>>("/legal-entities/").then((data) =>
      setEntities(data.results.filter((entity) => entity.entity_type !== "holding"))
    );
  }, []);

  const load = async () => {
    const params = new URLSearchParams();
    if (legalEntityId) params.set("legal_entity", legalEntityId);
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    const data = await api.get<TrialBalanceResponse>(`/journal-entries/trial_balance/?${params.toString()}`);
    setResult(data);
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div>
      <h1>{t("trialBalanceNav")}</h1>

      <div className="card">
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "end" }}>
          <div className="form-field">
            <label>{t("legalEntity")}</label>
            <select value={legalEntityId} onChange={(e) => setLegalEntityId(e.target.value)}>
              <option value="">{t("all")}</option>
              {entities.map((entity) => (
                <option key={entity.id} value={entity.id}>
                  {entity.code} — {entity.name}
                </option>
              ))}
            </select>
          </div>
          <div className="form-field">
            <label>{t("dateFrom")}</label>
            <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          </div>
          <div className="form-field">
            <label>{t("dateTo")}</label>
            <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
          </div>
          <button className="primary" onClick={load}>
            {t("submit")}
          </button>
        </div>
      </div>

      {result && (
        <table>
          <thead>
            <tr>
              <th>{t("code")}</th>
              <th>{t("name")}</th>
              <th>{t("debit")}</th>
              <th>{t("credit")}</th>
              <th>{t("balance")}</th>
            </tr>
          </thead>
          <tbody>
            {result.rows.map((row) => (
              <tr key={row.account_id}>
                <td>{row.account_code}</td>
                <td>{row.account_name}</td>
                <td><Money amount={row.debit} /></td>
                <td><Money amount={row.credit} /></td>
                <td><Money amount={row.balance} /></td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td colSpan={2}>
                <strong>{t("total")}</strong>
              </td>
              <td>
                <strong><Money amount={result.total_debit} /></strong>
              </td>
              <td>
                <strong><Money amount={result.total_credit} /></strong>
              </td>
              <td></td>
            </tr>
          </tfoot>
        </table>
      )}
    </div>
  );
}
