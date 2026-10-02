"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { Money } from "@/components/Money";
import { useLocale } from "@/lib/i18n";
import { flattenLeafAccounts, type FlatAccountOption } from "@/lib/accounts";
import type { AccountTreeNode, LedgerStatement } from "@/lib/types";

// Sprint 5.7 (CFO_REVIEW_1 C5): "دفتر الأستاذ" — GET /api/accounts/
// {id}/ledger/?legal_entity&from&to, same ledger_lines() service as
// treasury movements / party statements (5.4/5.6). Reached either
// directly (اختيار حساب ببحث) or via "الحركات" on a chart-of-accounts
// tree node (?account=<id> pre-fills the picker).
function LedgerReport() {
  const { t } = useLocale();
  const searchParams = useSearchParams();
  const [accounts, setAccounts] = useState<FlatAccountOption[]>([]);
  const [accountId, setAccountId] = useState(searchParams.get("account") || "");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [result, setResult] = useState<LedgerStatement | null>(null);

  useEffect(() => {
    api.get<AccountTreeNode[]>("/accounts/tree/").then((tree) => setAccounts(flattenLeafAccounts(tree)));
  }, []);

  const load = async () => {
    if (!accountId) return;
    const params = new URLSearchParams();
    if (dateFrom) params.set("from", dateFrom);
    if (dateTo) params.set("to", dateTo);
    const data = await api.get<LedgerStatement>(`/accounts/${accountId}/ledger/?${params.toString()}`);
    setResult(data);
  };

  useEffect(() => {
    if (accountId) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountId]);

  return (
    <div>
      <h1>{t("ledgerNav")}</h1>

      <div className="card">
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "end" }}>
          <div className="form-field" style={{ minWidth: "260px" }}>
            <label>{t("account")}</label>
            <select value={accountId} onChange={(e) => setAccountId(e.target.value)}> {/* form-ok: تصفية تقرير GET فقط، لا تحقق حقل من الـAPI */}
              <option value="" disabled>{t("selectAccount")}</option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>{a.label}</option>
              ))}
            </select>
          </div>
          <div className="form-field">
            <label>{t("dateFrom")}</label>
            <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} /> {/* form-ok: تصفية تقرير GET فقط، لا تحقق حقل من الـAPI */}
          </div>
          <div className="form-field">
            <label>{t("dateTo")}</label>
            <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} /> {/* form-ok: تصفية تقرير GET فقط، لا تحقق حقل من الـAPI */}
          </div>
          <button className="primary" onClick={load} disabled={!accountId}>{t("submit")}</button>
        </div>
      </div>

      {result && (
        <div className="card">
          <p>{t("openingBalance")}: <Money amount={result.opening_balance} /></p>
          {result.lines.length === 0 ? (
            <p style={{ color: "var(--muted)" }}>{t("noData")}</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>{t("date")}</th>
                  <th>{t("number")}</th>
                  <th>{t("description")}</th>
                  <th>{t("debitFc")}</th>
                  <th>{t("creditFc")}</th>
                  <th>{t("runningBalance")}</th>
                </tr>
              </thead>
              <tbody>
                {result.lines.map((line) => (
                  <tr key={`${line.entry_id}-${line.date}`}>
                    <td>{line.date}</td>
                    <td><Link href={`/dashboard/accounting/journal-entries/${line.entry_id}`}>{line.entry_number}</Link></td>
                    <td>{line.description}</td>
                    <td>{line.debit !== "0.00" ? <Money amount={line.debit} /> : ""}</td>
                    <td>{line.credit !== "0.00" ? <Money amount={line.credit} /> : ""}</td>
                    <td><Money amount={line.running_balance} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p style={{ marginTop: "0.5rem" }}><strong>{t("closingBalance")}: <Money amount={result.closing_balance} /></strong></p>
        </div>
      )}
    </div>
  );
}

export default function LedgerReportPage() {
  return (
    <Suspense fallback={null}>
      <LedgerReport />
    </Suspense>
  );
}
