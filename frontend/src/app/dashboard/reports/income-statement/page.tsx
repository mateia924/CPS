"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Money } from "@/components/Money";
import { useLocale } from "@/lib/i18n";
import type { IncomeStatementReport, LegalEntity, Paginated } from "@/lib/types";

export default function IncomeStatementPage() {
  const { t } = useLocale();
  const [entities, setEntities] = useState<LegalEntity[]>([]);
  const [legalEntityId, setLegalEntityId] = useState("");
  const [includeChildren, setIncludeChildren] = useState(true);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [result, setResult] = useState<IncomeStatementReport | null>(null);

  useEffect(() => {
    api.get<Paginated<LegalEntity>>("/legal-entities/").then((data) =>
      setEntities(data.results.filter((entity) => entity.entity_type !== "holding"))
    );
  }, []);

  const load = async () => {
    const params = new URLSearchParams();
    if (legalEntityId) params.set("legal_entity", legalEntityId);
    params.set("include_children", String(includeChildren));
    if (dateFrom) params.set("from", dateFrom);
    if (dateTo) params.set("to", dateTo);
    const data = await api.get<IncomeStatementReport>(`/reports/income-statement/?${params.toString()}`);
    setResult(data);
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div>
      <h1>{t("incomeStatementNav")}</h1>

      <div className="card">
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "end" }}>
          <div className="form-field">
            <label>{t("legalEntity")}</label>
            <select value={legalEntityId} onChange={(e) => setLegalEntityId(e.target.value)}> {/* form-ok: تصفية تقرير GET فقط، لا تحقق حقل من الـAPI */}
              <option value="">{t("all")}</option>
              {entities.map((entity) => (
                <option key={entity.id} value={entity.id}>{entity.code} — {entity.name}</option>
              ))}
            </select>
          </div>
          <div className="form-field">
            <label>
              <input type="checkbox" checked={includeChildren} onChange={(e) => setIncludeChildren(e.target.checked)} />{" "}{/* form-ok: تصفية تقرير GET فقط، لا تحقق حقل من الـAPI */}
              {t("includeChildren")}
            </label>
          </div>
          <div className="form-field">
            <label>{t("dateFrom")}</label>
            <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} /> {/* form-ok: تصفية تقرير GET فقط، لا تحقق حقل من الـAPI */}
          </div>
          <div className="form-field">
            <label>{t("dateTo")}</label>
            <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} /> {/* form-ok: تصفية تقرير GET فقط، لا تحقق حقل من الـAPI */}
          </div>
          <button className="primary" onClick={load}>{t("submit")}</button>
        </div>
      </div>

      {result && (
        <div className="card">
          <h3>{t("revenueType")}</h3>
          <table>
            <tbody>
              {result.revenue.map((row) => (
                <tr key={row.account_id}>
                  <td>{row.code} — {row.name}</td>
                  <td><Money amount={row.amount} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          <p><strong>{t("total")}: <Money amount={result.total_revenue} /></strong></p>

          <h3 style={{ marginTop: "1rem" }}>{t("expenseType")}</h3>
          <table>
            <tbody>
              {result.expense.map((row) => (
                <tr key={row.account_id}>
                  <td>{row.code} — {row.name}</td>
                  <td><Money amount={row.amount} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          <p><strong>{t("total")}: <Money amount={result.total_expense} /></strong></p>

          <p style={{ marginTop: "1rem", fontSize: "1.1rem" }}>
            <strong>{t("netIncome")}: <Money amount={result.net_income} /></strong>
          </p>

          <a
            href={`/print/reports/income-statement?${new URLSearchParams({
              ...(legalEntityId ? { legal_entity: legalEntityId } : {}),
              include_children: String(includeChildren),
              ...(dateFrom ? { from: dateFrom } : {}),
              ...(dateTo ? { to: dateTo } : {}),
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
